"""
auth/database.py — SQLite user store for Estrella PZ auth.

Schema:
    users           — user accounts
    reset_tokens    — password reset tokens (6-digit codes)
    login_attempts  — rate limiting for login

DB is created automatically in storage_root/users.db on first use.
Thread-safe: uses connection per call (sqlite3 check_same_thread=False + WAL mode).
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Optional


_lock = threading.Lock()
_db_path: Optional[Path] = None


def init_db(db_path: Path) -> None:
    """Create tables and run migrations. Call once at startup."""
    global _db_path
    _db_path = db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as con:
        con.executescript("""
            PRAGMA journal_mode=WAL;

            CREATE TABLE IF NOT EXISTS users (
                id              TEXT PRIMARY KEY,
                full_name       TEXT NOT NULL,
                company_name    TEXT NOT NULL DEFAULT '',
                email           TEXT NOT NULL UNIQUE,
                password_hash   TEXT NOT NULL,
                role            TEXT NOT NULL DEFAULT 'viewer',
                is_active       INTEGER NOT NULL DEFAULT 0,
                is_approved     INTEGER NOT NULL DEFAULT 0,
                email_verified  INTEGER NOT NULL DEFAULT 0,
                approval_status TEXT NOT NULL DEFAULT 'pending',
                created_at      TEXT NOT NULL,
                last_login      TEXT
            );

            CREATE TABLE IF NOT EXISTS reset_tokens (
                token      TEXT PRIMARY KEY,
                user_id    TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                used       INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS login_attempts (
                email       TEXT PRIMARY KEY,
                attempts    INTEGER NOT NULL DEFAULT 0,
                locked_until TEXT
            );
        """)
        # ── Idempotent column migrations (safe on existing DBs) ───────────────
        _add_column_if_missing(con, "users", "email_verified",  "INTEGER NOT NULL DEFAULT 0")
        _add_column_if_missing(con, "users", "approval_status", "TEXT NOT NULL DEFAULT 'pending'")
        # Back-fill approval_status from is_approved for rows created before migration
        con.execute("""
            UPDATE users SET approval_status = 'approved'
            WHERE is_approved = 1 AND approval_status = 'pending'
        """)


def _add_column_if_missing(con: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    """ALTER TABLE … ADD COLUMN only if the column does not already exist."""
    cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in cols:
        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(str(_db_path), check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def get_db() -> sqlite3.Connection:
    """Return a connection. Caller must close it (use as context manager)."""
    return _connect()
