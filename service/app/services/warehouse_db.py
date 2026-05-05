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
