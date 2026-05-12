"""
dhl_thread_lock.py — Per-thread reply lock for DHL self-clearance (P0).

Prevents the engine and operator from sending into the same DHL thread
simultaneously (Risk R5).

API
===
    acquire(thread_id, owner_actor, ttl_sec=3600) -> bool
        Atomically claim the lock for *owner_actor*. Returns True on success,
        False if a non-expired lock is held by someone else.

    release(thread_id, owner_actor) -> None
        Release the lock. The owner_actor MUST match the current holder.
        Mismatch raises LockOwnershipMismatch.

    force_release(thread_id, reason) -> None
        Operator-override path. Always succeeds; always writes an audit row.
        Use when the operator has manually sent a reply outside the engine.

    is_locked(thread_id) -> bool
        Read-only check. Considers TTL.

TTL extension is INTENTIONALLY NOT SUPPORTED. Callers must release and
re-acquire to renew. This prevents a runaway worker from holding indefinitely.

Storage
=======
SQLite, one row per thread_id. Schema:
    CREATE TABLE thread_locks (
        thread_id   TEXT PRIMARY KEY,
        owner_actor TEXT NOT NULL,
        acquired_at INTEGER NOT NULL,
        expires_at  INTEGER NOT NULL
    );
    CREATE TABLE thread_lock_audit (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        thread_id   TEXT    NOT NULL,
        event       TEXT    NOT NULL,    -- acquired|released|force_released|denied
        actor       TEXT    NOT NULL,
        reason      TEXT,
        at          INTEGER NOT NULL
    );

Concurrency: the SQLite connection is opened in IMMEDIATE transaction mode
for acquire(), so a parallel acquire() blocks at the SQL layer and only one
wins the row. Tested under high concurrency in test_dhl_thread_lock.py.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from ..core.config import settings

# Default TTL (acquire callers may override).
DEFAULT_TTL_SEC: int = 3600  # 1 hour


# ── Errors ───────────────────────────────────────────────────────────────────

class ThreadLockError(Exception):
    """Base for thread-lock errors."""


class LockOwnershipMismatch(ThreadLockError):
    """release() called by an actor other than the current holder."""


# ── Database location ────────────────────────────────────────────────────────

_DEFAULT_DB_NAME = "dhl_thread_locks.db"

# Per-process lock around the DB-path resolver to avoid races on first init.
_init_lock = threading.Lock()
_initialized_paths: set = set()


def _db_path() -> Path:
    return settings.storage_root / _DEFAULT_DB_NAME


def _ensure_initialised(path: Path) -> None:
    """Create the SQLite schema on first use for *path*."""
    if str(path) in _initialized_paths:
        return
    with _init_lock:
        if str(path) in _initialized_paths:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(path), timeout=30.0) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS thread_locks (
                    thread_id   TEXT PRIMARY KEY,
                    owner_actor TEXT NOT NULL,
                    acquired_at INTEGER NOT NULL,
                    expires_at  INTEGER NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS thread_lock_audit (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread_id   TEXT    NOT NULL,
                    event       TEXT    NOT NULL,
                    actor       TEXT    NOT NULL,
                    reason      TEXT,
                    at          INTEGER NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_thread_lock_audit_thread "
                "ON thread_lock_audit(thread_id)"
            )
            conn.commit()
        _initialized_paths.add(str(path))


@contextmanager
def _connect(db_path: Optional[Path] = None) -> Iterator[sqlite3.Connection]:
    path = db_path or _db_path()
    _ensure_initialised(path)
    conn = sqlite3.connect(str(path), timeout=30.0, isolation_level=None)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=10000")
        yield conn
    finally:
        conn.close()


def _now() -> int:
    return int(time.time())


def _write_audit(
    conn: sqlite3.Connection,
    thread_id: str,
    event: str,
    actor: str,
    reason: str = "",
) -> None:
    conn.execute(
        "INSERT INTO thread_lock_audit (thread_id, event, actor, reason, at) "
        "VALUES (?, ?, ?, ?, ?)",
        (thread_id, event, actor, reason, _now()),
    )


# ── Public API ───────────────────────────────────────────────────────────────

def acquire(
    thread_id:   str,
    owner_actor: str,
    ttl_sec:     int = DEFAULT_TTL_SEC,
    *,
    db_path:     Optional[Path] = None,
) -> bool:
    """
    Try to acquire the lock for *thread_id* on behalf of *owner_actor*.

    Returns True if acquired (newly or re-acquired by the same actor before
    TTL expiry). Returns False if a different actor holds an unexpired lock.

    Raises ValueError on empty arguments.
    """
    if not thread_id:
        raise ValueError("thread_id required")
    if not owner_actor:
        raise ValueError("owner_actor required")
    if ttl_sec <= 0:
        raise ValueError("ttl_sec must be > 0")

    now = _now()
    expires = now + ttl_sec

    with _connect(db_path) as conn:
        # IMMEDIATE transaction prevents two concurrent acquires from both winning.
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT owner_actor, expires_at FROM thread_locks WHERE thread_id=?",
                (thread_id,),
            ).fetchone()

            if row is not None:
                current_owner, current_expires = row
                if current_expires > now and current_owner != owner_actor:
                    _write_audit(conn, thread_id, "denied", owner_actor,
                                 f"held_by={current_owner}")
                    conn.execute("COMMIT")
                    return False
                # Same actor or expired: refresh.
                conn.execute(
                    "UPDATE thread_locks SET owner_actor=?, acquired_at=?, "
                    "expires_at=? WHERE thread_id=?",
                    (owner_actor, now, expires, thread_id),
                )
            else:
                conn.execute(
                    "INSERT INTO thread_locks (thread_id, owner_actor, "
                    "acquired_at, expires_at) VALUES (?, ?, ?, ?)",
                    (thread_id, owner_actor, now, expires),
                )

            _write_audit(conn, thread_id, "acquired", owner_actor, f"ttl_sec={ttl_sec}")
            conn.execute("COMMIT")
            return True
        except Exception:
            conn.execute("ROLLBACK")
            raise


def release(
    thread_id:   str,
    owner_actor: str,
    *,
    db_path:     Optional[Path] = None,
) -> None:
    """
    Release the lock. Owner must match the current holder.

    No-op if no lock is currently held (release after expiry is benign).
    Raises LockOwnershipMismatch if a different actor holds the lock.
    """
    if not thread_id or not owner_actor:
        raise ValueError("thread_id and owner_actor required")

    with _connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT owner_actor FROM thread_locks WHERE thread_id=?",
                (thread_id,),
            ).fetchone()
            if row is None:
                conn.execute("COMMIT")
                return
            current_owner = row[0]
            if current_owner != owner_actor:
                _write_audit(conn, thread_id, "denied", owner_actor,
                             f"release_held_by={current_owner}")
                conn.execute("COMMIT")
                raise LockOwnershipMismatch(
                    f"thread {thread_id!r} held by {current_owner!r}, "
                    f"cannot be released by {owner_actor!r}"
                )
            conn.execute("DELETE FROM thread_locks WHERE thread_id=?", (thread_id,))
            _write_audit(conn, thread_id, "released", owner_actor)
            conn.execute("COMMIT")
        except LockOwnershipMismatch:
            raise
        except Exception:
            conn.execute("ROLLBACK")
            raise


def force_release(
    thread_id: str,
    reason:    str,
    *,
    actor:     str = "operator",
    db_path:   Optional[Path] = None,
) -> None:
    """
    Operator-override release. Always succeeds. Always audit-logged.

    Used when the operator manually replied to a thread outside the engine,
    or when an automation crash left a stale lock.
    """
    if not thread_id:
        raise ValueError("thread_id required")
    if not reason:
        raise ValueError("reason required for force_release (audit trail)")

    with _connect(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("DELETE FROM thread_locks WHERE thread_id=?", (thread_id,))
            _write_audit(conn, thread_id, "force_released", actor, reason)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise


def is_locked(
    thread_id: str,
    *,
    db_path:   Optional[Path] = None,
) -> bool:
    """Read-only check. Considers TTL — expired locks return False."""
    now = _now()
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT expires_at FROM thread_locks WHERE thread_id=?",
            (thread_id,),
        ).fetchone()
    if row is None:
        return False
    return row[0] > now


def get_holder(
    thread_id: str,
    *,
    db_path:   Optional[Path] = None,
) -> Optional[str]:
    """Return the current owner_actor or None if not held (or expired)."""
    now = _now()
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT owner_actor, expires_at FROM thread_locks WHERE thread_id=?",
            (thread_id,),
        ).fetchone()
    if row is None:
        return None
    owner, expires = row
    if expires <= now:
        return None
    return owner


def get_audit(
    thread_id: str,
    *,
    db_path:   Optional[Path] = None,
    limit:     int = 50,
) -> list:
    """Return up to *limit* most-recent audit rows for *thread_id*."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT thread_id, event, actor, reason, at FROM thread_lock_audit "
            "WHERE thread_id=? ORDER BY id DESC LIMIT ?",
            (thread_id, int(limit)),
        ).fetchall()
    return [
        {"thread_id": r[0], "event": r[1], "actor": r[2], "reason": r[3], "at": r[4]}
        for r in rows
    ]
