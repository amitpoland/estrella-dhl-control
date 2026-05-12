"""
warehouse_db.py — Physical movement tracking for packing inventory.

Tables
------
warehouse_locations          declared physical locations (tray, shelf, bin)
inventory_current_location   one row per scannable physical piece
inventory_movement_events    append-only audit trail of every scan

Design rules
------------
- One DB file: storage_root/warehouse.db
- The scan_code is the unique key — same value the barcode label encodes,
  which is built from the packing row via the same algorithm as the
  /api/v1/packing/{batch_id}/barcode endpoint.
- Movement is physical only. Never touches invoice / PZ / wFirma values.
- All public functions return None / [] on misses; callers decide error UX.
- Thread-safe: per-call connection, WAL mode, threading.Lock.

Public API
----------
  init_warehouse_db(db_path)
  scan_code_for_packing_line(line) -> str
  find_packing_line_by_scan_code(scan_code) -> Optional[Dict]
  upsert_location(location_code, ...) -> str
  get_location(location_code) -> Optional[Dict]
  list_locations(active=True) -> List[Dict]
  record_scan(scan_code, action, to_location, operator, note) -> Dict
  get_current_location(scan_code) -> Optional[Dict]
  get_movement_history(scan_code) -> List[Dict]
"""
from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.logging import get_logger
from . import packing_db as pdb

log      = get_logger(__name__)
_lock    = threading.Lock()
_db_path: Optional[Path] = None

# Single source of truth for action → status.
# ALLOWED_ACTIONS is derived from this map so the two can never drift.
# Adding a new verb here automatically makes it valid; removing one makes it
# reject at the API boundary without any other change needed.
ACTION_STATUS_MAP: Dict[str, str] = {
    "RECEIVE":  "received",
    "MOVE":     "in_warehouse",
    "PICK":     "picked",
    "PACK":     "packed",
    "DISPATCH": "dispatched",
    "RETURN":   "returned",
}

ALLOWED_ACTIONS: frozenset = frozenset(ACTION_STATUS_MAP)


# ── Init ──────────────────────────────────────────────────────────────────────

def init_warehouse_db(db_path: Path) -> None:
    global _db_path
    _db_path = db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as con:
        con.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;

            -- ── Declared physical locations ─────────────────────────────────
            CREATE TABLE IF NOT EXISTS warehouse_locations (
                id              TEXT PRIMARY KEY,
                location_code   TEXT NOT NULL UNIQUE,
                location_type   TEXT NOT NULL DEFAULT 'tray',
                warehouse       TEXT NOT NULL DEFAULT 'MAIN',
                row_no          TEXT NOT NULL DEFAULT '',
                tray_id         TEXT NOT NULL DEFAULT '',
                description     TEXT NOT NULL DEFAULT '',
                active          INTEGER NOT NULL DEFAULT 1,
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_loc_active
                ON warehouse_locations (active);

            -- ── Current location of each scannable inventory item ───────────
            -- Dedup key: scan_code (one logical row per physical piece)
            CREATE TABLE IF NOT EXISTS inventory_current_location (
                id                TEXT PRIMARY KEY,
                batch_id          TEXT NOT NULL DEFAULT '',
                product_code      TEXT NOT NULL DEFAULT '',
                design_no         TEXT NOT NULL DEFAULT '',
                bag_id            TEXT NOT NULL DEFAULT '',
                pack_sr           REAL DEFAULT NULL,
                scan_code         TEXT NOT NULL UNIQUE,
                current_location  TEXT NOT NULL DEFAULT '',
                current_status    TEXT NOT NULL DEFAULT 'unknown',
                updated_at        TEXT NOT NULL,
                updated_by        TEXT NOT NULL DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_icl_batch
                ON inventory_current_location (batch_id);
            CREATE INDEX IF NOT EXISTS idx_icl_location
                ON inventory_current_location (current_location);

            -- ── Append-only movement audit trail ────────────────────────────
            CREATE TABLE IF NOT EXISTS inventory_movement_events (
                id              TEXT PRIMARY KEY,
                batch_id        TEXT NOT NULL DEFAULT '',
                scan_code       TEXT NOT NULL,
                action          TEXT NOT NULL,
                from_location   TEXT NOT NULL DEFAULT '',
                to_location     TEXT NOT NULL DEFAULT '',
                operator        TEXT NOT NULL DEFAULT '',
                event_time      TEXT NOT NULL,
                note            TEXT NOT NULL DEFAULT '',
                created_at      TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_ime_scan_code
                ON inventory_movement_events (scan_code, event_time);
            CREATE INDEX IF NOT EXISTS idx_ime_batch
                ON inventory_movement_events (batch_id);

            -- ── Lifecycle state per inventory item (one row per scan_code) ──
            -- Independent from physical movement above. Tracks the commercial
            -- lifecycle: PURCHASE_TRANSIT → WAREHOUSE_STOCK → SALES_TRANSIT → CLOSED.
            -- Enforced single-state-per-item via UNIQUE(scan_code).
            CREATE TABLE IF NOT EXISTS inventory_state (
                id              TEXT PRIMARY KEY,
                scan_code       TEXT NOT NULL UNIQUE,
                product_code    TEXT NOT NULL DEFAULT '',
                design_no       TEXT NOT NULL DEFAULT '',
                batch_id        TEXT NOT NULL DEFAULT '',
                state           TEXT NOT NULL,
                updated_at      TEXT NOT NULL,
                updated_by      TEXT NOT NULL DEFAULT '',
                note            TEXT NOT NULL DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_invstate_state
                ON inventory_state (state);
            CREATE INDEX IF NOT EXISTS idx_invstate_batch
                ON inventory_state (batch_id);
            CREATE INDEX IF NOT EXISTS idx_invstate_product
                ON inventory_state (product_code);

            -- Append-only audit trail of every state transition.
            CREATE TABLE IF NOT EXISTS inventory_state_events (
                id              TEXT PRIMARY KEY,
                scan_code       TEXT NOT NULL,
                from_state      TEXT NOT NULL DEFAULT '',
                to_state        TEXT NOT NULL,
                trigger         TEXT NOT NULL,
                occurred_at     TEXT NOT NULL,
                operator        TEXT NOT NULL DEFAULT '',
                note            TEXT NOT NULL DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_invstate_events_scan
                ON inventory_state_events (scan_code, occurred_at);
        """)


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(str(_db_path), check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── scan_code computation (mirror of routes_packing._barcode_value) ──────────

def scan_code_for_packing_line(line: Dict[str, Any]) -> str:
    """
    Compute the scan_code for a packing row.

    Same algorithm as routes_packing._barcode_value — kept here to avoid
    circular imports.

    Priority:
      1. <product_code>|<bag_id>                 (bag tracking)
      2. <product_code>|sr<pack_sr>|<design_no>  (aggregated invoice)
      3. <product_code>|<design_no>              (no bag, no Sr)
      4. <product_code>                          (last resort)
    """
    pc     = str(line.get("product_code") or "")
    bag    = str(line.get("bag_id") or "")
    sr     = line.get("pack_sr")
    design = str(line.get("design_no") or "")

    if bag:
        return f"{pc}|{bag}"
    if sr is not None and sr != "":
        try:
            sr_str = str(int(sr)) if float(sr).is_integer() else str(sr)
        except (TypeError, ValueError):
            sr_str = str(sr)
        if design:
            return f"{pc}|sr{sr_str}|{design}"
        return f"{pc}|sr{sr_str}"
    if design:
        return f"{pc}|{design}"
    return pc


def find_packing_line_by_scan_code(
    scan_code: str,
    batch_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Resolve a scan_code to its source packing_lines row.

    *batch_id* — when provided, scopes the lookup to a single batch.
    Use this whenever the scanner knows which batch is being processed:
    the same scan_code can appear in multiple batches when pack_sr is
    absent and shipment data is reused across test or recurring shipments.

    Fast path (O(1)): uses the pre-computed scan_code column.
    Fallback path (O(n_product_code)): legacy NULL scan_code rows.
    """
    if not scan_code:
        return None

    # ── Fast path ────────────────────────────────────────────────────────────
    row = pdb.get_packing_line_by_scan_code(scan_code, batch_id=batch_id)
    if row is not None:
        return row

    # ── Fallback: legacy rows where scan_code column is NULL ─────────────────
    pc = scan_code.split("|", 1)[0]
    if not pc or pdb._db_path is None:
        return None

    try:
        with sqlite3.connect(str(pdb._db_path), check_same_thread=False) as pcon:
            pcon.row_factory = sqlite3.Row
            if batch_id:
                rows = pcon.execute(
                    "SELECT * FROM packing_lines WHERE product_code=? AND batch_id=? AND scan_code IS NULL",
                    (pc, batch_id),
                ).fetchall()
            else:
                rows = pcon.execute(
                    "SELECT * FROM packing_lines WHERE product_code=? AND scan_code IS NULL",
                    (pc,),
                ).fetchall()
    except Exception as exc:
        log.warning("find_packing_line_by_scan_code fallback DB error: %s", exc)
        return None

    for r in rows:
        d = dict(r)
        if scan_code_for_packing_line(d) == scan_code:
            try:
                pdb.backfill_scan_codes()
            except Exception:
                pass
            return d
    return None


# ── Locations ────────────────────────────────────────────────────────────────

def upsert_location(
    location_code: str,
    *,
    location_type: str = "tray",
    warehouse:     str = "MAIN",
    row_no:        str = "",
    tray_id:       str = "",
    description:   str = "",
    active:        bool = True,
) -> str:
    """Insert or update a warehouse location. Returns location id."""
    if _db_path is None or not location_code:
        return ""
    now = _now()
    with _lock, _connect() as con:
        existing = con.execute(
            "SELECT id FROM warehouse_locations WHERE location_code=?",
            (location_code,),
        ).fetchone()
        if existing:
            con.execute(
                """UPDATE warehouse_locations
                   SET location_type=?, warehouse=?, row_no=?, tray_id=?,
                       description=?, active=?, updated_at=?
                   WHERE id=?""",
                (location_type, warehouse, row_no, tray_id, description,
                 1 if active else 0, now, existing["id"]),
            )
            return existing["id"]
        loc_id = str(uuid.uuid4())
        con.execute(
            """INSERT INTO warehouse_locations
               (id, location_code, location_type, warehouse, row_no, tray_id,
                description, active, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (loc_id, location_code, location_type, warehouse, row_no, tray_id,
             description, 1 if active else 0, now, now),
        )
        return loc_id


def get_location(location_code: str) -> Optional[Dict[str, Any]]:
    if _db_path is None or not location_code:
        return None
    with _connect() as con:
        row = con.execute(
            "SELECT * FROM warehouse_locations WHERE location_code=?",
            (location_code,),
        ).fetchone()
    return dict(row) if row else None


def list_locations(active: Optional[bool] = True) -> List[Dict[str, Any]]:
    if _db_path is None:
        return []
    with _connect() as con:
        if active is None:
            rows = con.execute(
                "SELECT * FROM warehouse_locations ORDER BY warehouse, location_code"
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM warehouse_locations WHERE active=? ORDER BY warehouse, location_code",
                (1 if active else 0,),
            ).fetchall()
    return [dict(r) for r in rows]


# ── Scan / movement ──────────────────────────────────────────────────────────

def _status_for_action(action: str) -> str:
    """
    Return the current_status string for a validated action verb.

    Raises ValueError for any action not in ACTION_STATUS_MAP. This should
    never trigger in production (the API layer validates via ALLOWED_ACTIONS
    before calling record_scan), but it prevents a silent wrong-status write
    if the two ever drift.
    """
    try:
        return ACTION_STATUS_MAP[action.upper()]
    except KeyError:
        raise ValueError(
            f"Action {action!r} has no status mapping. "
            f"Add it to ACTION_STATUS_MAP in warehouse_db.py."
        )


def record_scan(
    *,
    scan_code:   str,
    action:      str,
    to_location: str = "",
    operator:    str = "",
    note:        str = "",
    batch_id:    Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Atomically:
      1. Soft-validate to_location against warehouse_locations.
         Unknown location is allowed; result includes unknown_location=True
         and the event note is prefixed with a warning.
      2. Upsert inventory_current_location (one row per scan_code).
      3. Append inventory_movement_events.

    Returns the resulting current-location row (augmented with
    unknown_location: bool), or None if scan_code is unknown to
    packing_lines (caller should respond 404).
    """
    if _db_path is None:
        raise RuntimeError("warehouse_db not initialised")
    if not scan_code:
        return None
    action = (action or "").upper().strip()
    if action not in ALLOWED_ACTIONS:
        raise ValueError(
            f"Unknown action {action!r}. Allowed: {sorted(ALLOWED_ACTIONS)}"
        )

    pl = find_packing_line_by_scan_code(scan_code, batch_id=batch_id)
    if not pl:
        return None

    new_status   = _status_for_action(action)
    now          = _now()
    batch_id     = pl.get("batch_id", "")
    product_code = pl.get("product_code", "")
    design_no    = pl.get("design_no", "")
    bag_id       = pl.get("bag_id", "")
    pack_sr      = pl.get("pack_sr")

    with _lock, _connect() as con:
        # 1. Soft location validation — one indexed read, never blocks the scan
        unknown_location = False
        if to_location:
            loc_row = con.execute(
                "SELECT id FROM warehouse_locations WHERE location_code=? AND active=1",
                (to_location,),
            ).fetchone()
            if loc_row is None:
                unknown_location = True
                warn = f"[UNKNOWN_LOCATION: {to_location!r}]"
                note = f"{warn} {note}".strip() if note else warn
                log.warning(
                    "scan %r → undeclared location %r (action=%s, operator=%s)",
                    scan_code, to_location, action, operator,
                )

        # 2. Read current state for from_location
        prev = con.execute(
            "SELECT * FROM inventory_current_location WHERE scan_code=?",
            (scan_code,),
        ).fetchone()
        from_location = prev["current_location"] if prev else ""

        # 3. Upsert current location
        if prev:
            con.execute(
                """UPDATE inventory_current_location
                   SET current_location=?, current_status=?,
                       updated_at=?, updated_by=?
                   WHERE id=?""",
                (to_location, new_status, now, operator, prev["id"]),
            )
            icl_id = prev["id"]
        else:
            icl_id = str(uuid.uuid4())
            con.execute(
                """INSERT INTO inventory_current_location
                   (id, batch_id, product_code, design_no, bag_id, pack_sr,
                    scan_code, current_location, current_status,
                    updated_at, updated_by)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (icl_id, batch_id, product_code, design_no, bag_id, pack_sr,
                 scan_code, to_location, new_status, now, operator),
            )

        # 4. Append movement event (note carries the UNKNOWN_LOCATION warning if set)
        evt_id = str(uuid.uuid4())
        con.execute(
            """INSERT INTO inventory_movement_events
               (id, batch_id, scan_code, action, from_location, to_location,
                operator, event_time, note, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (evt_id, batch_id, scan_code, action, from_location, to_location,
             operator, now, note, now),
        )

        # 5. Return updated row, augmented with soft-validation flag
        row = con.execute(
            "SELECT * FROM inventory_current_location WHERE id=?",
            (icl_id,),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["unknown_location"] = unknown_location
        return result


def get_current_location(scan_code: str) -> Optional[Dict[str, Any]]:
    if _db_path is None or not scan_code:
        return None
    with _connect() as con:
        row = con.execute(
            "SELECT * FROM inventory_current_location WHERE scan_code=?",
            (scan_code,),
        ).fetchone()
    return dict(row) if row else None


# ── Idempotent-write helpers (Option A — DB-level UNIQUE constraint) ─────
#
# Used by service/app/services/inventory_location_writer.py for Move stock.
# Requires the migration in
# service/app/db/migrations/draft_20260512_002516_idempotency_key.py.draft
# to have been applied (column + partial UNIQUE index present).
#
# Discipline: these helpers do NOT call inventory_state_engine.transition().
# Lifecycle state is the engine's single-writer domain. These write only
# physical movement metadata.

def record_scan_with_idempotency(
    *,
    scan_code:        str,
    action:           str,
    to_location:      str,
    operator:         str,
    idempotency_key:  str,
    note:             str = "",
    batch_id:         Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Like ``record_scan`` but persists an ``idempotency_key`` on the
    movement event. Raises ``sqlite3.IntegrityError`` if the partial
    UNIQUE index on (scan_code, idempotency_key) catches a duplicate;
    callers should treat that as the replay signal and look up the
    existing event with ``find_movement_event_by_idempotency``.

    No app-level lock. The database UNIQUE constraint serialises
    duplicate writes under SQLite WAL — exactly one INSERT wins.

    Returns the resulting current-location row dict (augmented with
    ``unknown_location: bool``), or ``None`` if the scan_code is
    unknown to packing_lines (caller should respond 404).
    """
    if _db_path is None:
        raise RuntimeError("warehouse_db not initialised")
    if not scan_code:
        return None
    if not idempotency_key:
        raise ValueError("idempotency_key is required for record_scan_with_idempotency")
    action = (action or "").upper().strip()
    if action not in ALLOWED_ACTIONS:
        raise ValueError(
            f"Unknown action {action!r}. Allowed: {sorted(ALLOWED_ACTIONS)}"
        )

    pl = find_packing_line_by_scan_code(scan_code, batch_id=batch_id)
    if not pl:
        return None

    new_status   = _status_for_action(action)
    now          = _now()
    batch_id     = pl.get("batch_id", "")
    product_code = pl.get("product_code", "")
    design_no    = pl.get("design_no", "")
    bag_id       = pl.get("bag_id", "")
    pack_sr      = pl.get("pack_sr")

    with _connect() as con:
        # Soft location validation
        unknown_location = False
        if to_location:
            loc_row = con.execute(
                "SELECT id FROM warehouse_locations WHERE location_code=? AND active=1",
                (to_location,),
            ).fetchone()
            if loc_row is None:
                unknown_location = True
                warn = f"[UNKNOWN_LOCATION: {to_location!r}]"
                note = f"{warn} {note}".strip() if note else warn

        # Read current state for from_location
        prev = con.execute(
            "SELECT * FROM inventory_current_location WHERE scan_code=?",
            (scan_code,),
        ).fetchone()
        from_location = prev["current_location"] if prev else ""

        # Single transaction: INSERT event first (the UNIQUE constraint
        # acts here). If it raises, the transaction rolls back and the
        # location upsert never happens — the caller handles replay.
        evt_id = str(uuid.uuid4())
        con.execute(
            """INSERT INTO inventory_movement_events
               (id, batch_id, scan_code, action, from_location, to_location,
                operator, event_time, note, created_at, idempotency_key)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (evt_id, batch_id, scan_code, action, from_location, to_location,
             operator, now, note, now, idempotency_key),
        )

        # Insert succeeded — proceed with location upsert in the same txn.
        if prev:
            con.execute(
                """UPDATE inventory_current_location
                   SET current_location=?, current_status=?,
                       updated_at=?, updated_by=?
                   WHERE id=?""",
                (to_location, new_status, now, operator, prev["id"]),
            )
            icl_id = prev["id"]
        else:
            icl_id = str(uuid.uuid4())
            con.execute(
                """INSERT INTO inventory_current_location
                   (id, batch_id, product_code, design_no, bag_id, pack_sr,
                    scan_code, current_location, current_status,
                    updated_at, updated_by)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (icl_id, batch_id, product_code, design_no, bag_id, pack_sr,
                 scan_code, to_location, new_status, now, operator),
            )

        con.commit()

        row = con.execute(
            "SELECT * FROM inventory_current_location WHERE id=?",
            (icl_id,),
        ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["unknown_location"] = unknown_location
        result["event_id"] = evt_id
        result["from_location"] = from_location
        return result


def find_movement_event_by_idempotency(
    scan_code: str, idempotency_key: str
) -> Optional[Dict[str, Any]]:
    """Return the movement event matching ``(scan_code, idempotency_key)``,
    or ``None``. Read-only; used by the replay path in the Move stock
    writer after an ``IntegrityError`` from
    ``record_scan_with_idempotency``.
    """
    if _db_path is None or not scan_code or not idempotency_key:
        return None
    with _connect() as con:
        row = con.execute(
            "SELECT * FROM inventory_movement_events "
            "WHERE scan_code=? AND idempotency_key=?",
            (scan_code, idempotency_key),
        ).fetchone()
    return dict(row) if row else None


# Module-level cache. Once the precheck succeeds, the column + index
# can't disappear at runtime (SQLite doesn't drop columns silently),
# so we never need to re-check. Failure does NOT cache — a runtime
# migration apply during operator triage will be picked up on the
# next request. Tests reset this via patching the function directly.
_idempotency_schema_verified = False


def ensure_idempotency_schema() -> bool:
    """Return True iff `inventory_movement_events.idempotency_key`
    column AND `idx_movement_idempotency` index both exist.

    Used by the Move stock write path as a pre-write guard. Callers
    that get False should respond with HTTP 503 MIGRATION_PENDING
    rather than letting the downstream ``INSERT`` raise a raw
    ``sqlite3.OperationalError`` (column missing) that leaks SQL
    text and traceback to the client.

    Never raises. Reading PRAGMA + sqlite_master is read-only and
    cheap; the result is cached at module scope once verified.
    """
    global _idempotency_schema_verified
    if _idempotency_schema_verified:
        return True
    if _db_path is None:
        return False
    try:
        with _connect() as con:
            cols = [
                r[1] for r in
                con.execute("PRAGMA table_info(inventory_movement_events)").fetchall()
            ]
            if "idempotency_key" not in cols:
                return False
            row = con.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND name='idx_movement_idempotency'"
            ).fetchone()
            if row is None:
                return False
    except Exception:
        return False
    _idempotency_schema_verified = True
    return True


def get_movement_history(scan_code: str) -> List[Dict[str, Any]]:
    if _db_path is None or not scan_code:
        return []
    with _connect() as con:
        rows = con.execute(
            """SELECT * FROM inventory_movement_events
               WHERE scan_code=? ORDER BY event_time""",
            (scan_code,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_inventory_at_location(location_code: str) -> List[Dict[str, Any]]:
    """All scannable items currently sitting at the given location."""
    if _db_path is None or not location_code:
        return []
    with _connect() as con:
        rows = con.execute(
            """SELECT * FROM inventory_current_location
               WHERE current_location=?
               ORDER BY updated_at DESC""",
            (location_code,),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Sample-out helpers (Phase B.1) ───────────────────────────────────────
#
# These helpers read/write sample_out_events. They do NOT mutate
# inventory_state — that goes through inventory_state_engine.transition()
# (single-writer discipline). The writer in inventory_sample_writer.py
# calls transition() AND then calls record_sample_out_event() here to
# capture the Sample-out-specific evidence in the dedicated event table.
#
# Migration:
#   service/app/db/migrations/draft_20260512_122327_sample_out_events.py.draft
#   must be applied before these helpers can run in production.

_sample_out_schema_verified = False


def ensure_sample_out_schema() -> bool:
    """Return True iff `sample_out_events` table AND
    `idx_sample_out_idempotency` index both exist. Cached on success.

    Used by the Sample-out writer as a pre-write guard, same pattern as
    `ensure_idempotency_schema()` for Move stock. Callers that get False
    should respond with HTTP 503 MIGRATION_PENDING.

    Never raises.
    """
    global _sample_out_schema_verified
    if _sample_out_schema_verified:
        return True
    if _db_path is None:
        return False
    try:
        with _connect() as con:
            tbl = con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='sample_out_events'"
            ).fetchone()
            if tbl is None:
                return False
            idx = con.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND name='idx_sample_out_idempotency'"
            ).fetchone()
            if idx is None:
                return False
    except Exception:
        return False
    _sample_out_schema_verified = True
    return True


def record_sample_out_event(
    *,
    scan_code:               str,
    direction:               str,        # 'out' | 'return'
    operator:                str,
    recipient_client_name:   str = "",
    recipient_client_id:     str = "",
    sample_reason:           str = "",
    expected_return_date:    str = "",
    notes:                   str = "",
    idempotency_key:         str = "",
    linked_state_event_id:   str = "",
    linked_origin_event_id:  str = "",
) -> Dict[str, Any]:
    """Append a row to sample_out_events. Raises sqlite3.IntegrityError
    if the partial UNIQUE index on (scan_code, idempotency_key) catches
    a duplicate; caller treats that as the replay signal.

    Returns the inserted row as a dict. Never mutates inventory_state.
    """
    if _db_path is None:
        raise RuntimeError("warehouse_db not initialised")
    if not scan_code:
        raise ValueError("scan_code is required")
    if direction not in ("out", "return"):
        raise ValueError(f"direction must be 'out' or 'return', got {direction!r}")
    if not idempotency_key:
        raise ValueError("idempotency_key is required for record_sample_out_event")

    now = _now()
    evt_id = str(uuid.uuid4())
    with _connect() as con:
        con.execute(
            """INSERT INTO sample_out_events
               (id, scan_code, direction, operator,
                recipient_client_name, recipient_client_id, sample_reason,
                expected_return_date, notes, idempotency_key,
                linked_state_event_id, linked_origin_event_id,
                occurred_at, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (evt_id, scan_code, direction, operator,
             recipient_client_name, recipient_client_id, sample_reason,
             expected_return_date, notes, idempotency_key,
             linked_state_event_id, linked_origin_event_id,
             now, now),
        )
        con.commit()
        row = con.execute(
            "SELECT * FROM sample_out_events WHERE id=?", (evt_id,)
        ).fetchone()
    return dict(row) if row else {"id": evt_id}


def find_sample_out_event_by_idempotency(
    scan_code: str, idempotency_key: str
) -> Optional[Dict[str, Any]]:
    """Return the prior sample_out_events row matching
    (scan_code, idempotency_key), or None. Replay lookup used by the
    Sample-out writer after IntegrityError."""
    if _db_path is None or not scan_code or not idempotency_key:
        return None
    with _connect() as con:
        row = con.execute(
            "SELECT * FROM sample_out_events "
            "WHERE scan_code=? AND idempotency_key=?",
            (scan_code, idempotency_key),
        ).fetchone()
    return dict(row) if row else None


def find_origin_sample_out_event(scan_code: str) -> Optional[Dict[str, Any]]:
    """Find the most recent 'out' event for a scan_code that has NOT
    yet been paired with a 'return' event. Used by sample-return to
    link the return audit row to the originating out event."""
    if _db_path is None or not scan_code:
        return None
    with _connect() as con:
        row = con.execute(
            """SELECT * FROM sample_out_events
               WHERE scan_code=? AND direction='out'
               AND id NOT IN (
                   SELECT linked_origin_event_id FROM sample_out_events
                   WHERE scan_code=? AND direction='return'
                     AND linked_origin_event_id != ''
               )
               ORDER BY occurred_at DESC LIMIT 1""",
            (scan_code, scan_code),
        ).fetchone()
    return dict(row) if row else None


def count_open_overdue_samples_for_recipient(
    recipient_client_name: str, threshold_iso: str
) -> int:
    """Count open (not-yet-returned) sample-out events for a given
    recipient whose `expected_return_date` is at or before
    `threshold_iso`. Used to enforce the 30-day block-new rule:
    when count > 0, new sample-outs to the same recipient are rejected.

    Open = an 'out' event with no matching 'return' event."""
    if _db_path is None or not (recipient_client_name or "").strip():
        return 0
    with _connect() as con:
        row = con.execute(
            """SELECT COUNT(*) AS n FROM sample_out_events o
               WHERE o.recipient_client_name = ?
                 AND o.direction = 'out'
                 AND o.expected_return_date != ''
                 AND o.expected_return_date <= ?
                 AND NOT EXISTS (
                   SELECT 1 FROM sample_out_events r
                   WHERE r.scan_code = o.scan_code
                     AND r.direction = 'return'
                     AND r.occurred_at >= o.occurred_at
                 )""",
            (recipient_client_name, threshold_iso),
        ).fetchone()
    return int(row["n"]) if row else 0
