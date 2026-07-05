"""DRAFT migration — add idempotency_key column + partial UNIQUE index
to inventory_movement_events.

Project has NO alembic (verified — no alembic.ini, no migrations dir
with versioned scripts). Schema evolution today is via
`CREATE TABLE IF NOT EXISTS` blocks in `init_warehouse_db()` plus
the column-add-if-missing pattern from `auth/database.py:71-75`.

This file is `.py.draft` — NOT picked up by any import or autoloader.
Operator runs `python -m service.app.db.migrations.draft_20260512_002516_idempotency_key`
manually after morning review (after renaming to `.py`), OR copies
the body of `upgrade()` into `init_warehouse_db()` for permanent
schema integration.

Idempotent: safe to run multiple times.

Option A from REVIEW_FAILED_feat_inventory-button-move-stock.md:
  - Adds `idempotency_key TEXT NOT NULL DEFAULT ''` to
    `inventory_movement_events`.
  - Creates partial UNIQUE INDEX on `(scan_code, idempotency_key)`
    WHERE idempotency_key != ''. Pre-existing rows (empty key)
    are excluded from the constraint. New rows with non-empty
    key get UNIQUE enforcement.

Why partial: existing rows from `record_scan()` (the legacy writer)
don't carry idempotency_key and never will. Empty-key rows must not
collide. SQLite supports partial indexes since 3.8.0; this project
runs on `journal_mode=WAL` (warehouse_db.py:72) which implies a
modern SQLite.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path


# Forward declaration so the module-level docstring can reference the
# revision id. No external migration runner exists; the id is for
# operator/audit reference only.
REVISION = "20260512_002516_idempotency_key"
DESCRIPTION = "Add idempotency_key column + partial UNIQUE index to inventory_movement_events"


def _column_exists(con: sqlite3.Connection, table: str, column: str) -> bool:
    cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()]
    return column in cols


def _index_exists(con: sqlite3.Connection, index_name: str) -> bool:
    row = con.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
        (index_name,),
    ).fetchone()
    return row is not None


def upgrade(db_path: Path) -> None:
    """Apply the migration to the warehouse.db at `db_path`. Idempotent."""
    con = sqlite3.connect(str(db_path))
    try:
        if not _column_exists(con, "inventory_movement_events", "idempotency_key"):
            con.execute(
                "ALTER TABLE inventory_movement_events "
                "ADD COLUMN idempotency_key TEXT NOT NULL DEFAULT ''"
            )
            print(f"[{REVISION}] Added column inventory_movement_events.idempotency_key")
        else:
            print(f"[{REVISION}] Column inventory_movement_events.idempotency_key already exists")

        if not _index_exists(con, "idx_movement_idempotency"):
            con.execute(
                "CREATE UNIQUE INDEX idx_movement_idempotency "
                "ON inventory_movement_events (scan_code, idempotency_key) "
                "WHERE idempotency_key != ''"
            )
            print(f"[{REVISION}] Created partial UNIQUE index idx_movement_idempotency")
        else:
            print(f"[{REVISION}] Index idx_movement_idempotency already exists")

        con.commit()
    finally:
        con.close()


def downgrade(db_path: Path) -> None:
    """Reverse the migration. SQLite has no DROP COLUMN before 3.35,
    so this drops the index only; the (empty-default) column is left
    in place and is harmless.
    """
    con = sqlite3.connect(str(db_path))
    try:
        if _index_exists(con, "idx_movement_idempotency"):
            con.execute("DROP INDEX idx_movement_idempotency")
            print(f"[{REVISION}] Dropped index idx_movement_idempotency")
        con.commit()
        print(
            f"[{REVISION}] WARNING: idempotency_key column NOT dropped "
            "(SQLite <3.35 has no DROP COLUMN). Column remains with "
            "empty-string default — harmless if reapplied later."
        )
    finally:
        con.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <path-to-warehouse.db> [up|down]")
        sys.exit(2)
    target = Path(sys.argv[1])
    direction = sys.argv[2] if len(sys.argv) > 2 else "up"
    if not target.exists():
        print(f"ERROR: db not found at {target}")
        sys.exit(1)
    if direction == "up":
        upgrade(target)
    elif direction == "down":
        downgrade(target)
    else:
        print(f"Unknown direction: {direction!r}; expected 'up' or 'down'")
        sys.exit(2)
