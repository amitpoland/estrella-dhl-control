"""
inventory_state_engine.py — Lifecycle state model for PZ inventory.

Tracks each scannable item through its commercial lifecycle, independent of
physical-location tracking in warehouse_db.

States
------
  PURCHASE_TRANSIT   PZ generated, goods on the way from supplier
  WAREHOUSE_STOCK    Goods received at warehouse
  SALES_TRANSIT      Sales invoice issued, goods on the way to customer
  CLOSED             Delivery confirmed, sale complete (terminal)

Transitions (only these are legal; everything else raises)
----------
  None              → PURCHASE_TRANSIT     trigger: pz_generated
  PURCHASE_TRANSIT  → WAREHOUSE_STOCK      trigger: warehouse_receive
  WAREHOUSE_STOCK   → SALES_TRANSIT        trigger: invoice_issued
  SALES_TRANSIT     → CLOSED               trigger: delivery_confirmed

Invariants
----------
- One scan_code = exactly one current state (UNIQUE constraint).
- States are explicit and persisted; never inferred from other tables.
- No financial values touched here.
- Identity supports product_code + design_no + scan_code; scan_code is the key.

Public API
----------
  transition(scan_code, to_state, trigger, *, product_code, design_no,
             batch_id, operator, note) -> Dict
  get_state(scan_code) -> Optional[Dict]
  list_by_state(state, batch_id=None) -> List[Dict]
  count_by_state(batch_id=None) -> Dict[str, int]
  get_history(scan_code) -> List[Dict]
"""
from __future__ import annotations

import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import warehouse_db as wdb

# ── State constants ──────────────────────────────────────────────────────────

PURCHASE_TRANSIT = "PURCHASE_TRANSIT"
WAREHOUSE_STOCK  = "WAREHOUSE_STOCK"
SALES_TRANSIT    = "SALES_TRANSIT"
CLOSED           = "CLOSED"

STATES: frozenset = frozenset({
    PURCHASE_TRANSIT, WAREHOUSE_STOCK, SALES_TRANSIT, CLOSED,
})

# Map: from_state (or None for first entry) → set of legal to_states.
LEGAL_TRANSITIONS: Dict[Optional[str], frozenset] = {
    None:             frozenset({PURCHASE_TRANSIT}),
    PURCHASE_TRANSIT: frozenset({WAREHOUSE_STOCK}),
    WAREHOUSE_STOCK:  frozenset({SALES_TRANSIT}),
    SALES_TRANSIT:    frozenset({CLOSED}),
    CLOSED:           frozenset(),
}

# Default trigger label for each transition; callers may override.
DEFAULT_TRIGGER: Dict[tuple, str] = {
    (None,             PURCHASE_TRANSIT): "pz_generated",
    (PURCHASE_TRANSIT, WAREHOUSE_STOCK):  "warehouse_receive",
    (WAREHOUSE_STOCK,  SALES_TRANSIT):    "invoice_issued",
    (SALES_TRANSIT,    CLOSED):           "delivery_confirmed",
}

_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    if wdb._db_path is None:
        raise RuntimeError("warehouse_db not initialised — call init_warehouse_db() first")
    con = sqlite3.connect(str(wdb._db_path), check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


# ── Public API ───────────────────────────────────────────────────────────────

def get_state(scan_code: str) -> Optional[Dict[str, Any]]:
    """Return the current state row for *scan_code*, or None if unknown."""
    if not scan_code:
        return None
    with _connect() as con:
        row = con.execute(
            "SELECT * FROM inventory_state WHERE scan_code=?",
            (scan_code,),
        ).fetchone()
    return dict(row) if row else None


def get_history(scan_code: str) -> List[Dict[str, Any]]:
    """Append-only event history for *scan_code*."""
    if not scan_code:
        return []
    with _connect() as con:
        rows = con.execute(
            """SELECT * FROM inventory_state_events
               WHERE scan_code=? ORDER BY occurred_at""",
            (scan_code,),
        ).fetchall()
    return [dict(r) for r in rows]


def list_by_state(state: str, batch_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Items currently in *state*, optionally scoped to a batch."""
    if state not in STATES:
        raise ValueError(f"Unknown state {state!r}. Allowed: {sorted(STATES)}")
    with _connect() as con:
        if batch_id:
            rows = con.execute(
                "SELECT * FROM inventory_state WHERE state=? AND batch_id=?",
                (state, batch_id),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM inventory_state WHERE state=?",
                (state,),
            ).fetchall()
    return [dict(r) for r in rows]


def count_by_state(batch_id: Optional[str] = None) -> Dict[str, int]:
    """Disjoint counts per state. Sum equals total tracked items."""
    counts = {s: 0 for s in STATES}
    with _connect() as con:
        if batch_id:
            rows = con.execute(
                "SELECT state, COUNT(*) AS n FROM inventory_state "
                "WHERE batch_id=? GROUP BY state",
                (batch_id,),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT state, COUNT(*) AS n FROM inventory_state GROUP BY state"
            ).fetchall()
    for r in rows:
        if r["state"] in counts:
            counts[r["state"]] = r["n"]
    return counts


def transition(
    *,
    scan_code:    str,
    to_state:     str,
    trigger:      Optional[str] = None,
    product_code: str = "",
    design_no:    str = "",
    batch_id:     str = "",
    operator:     str = "",
    note:         str = "",
) -> Dict[str, Any]:
    """
    Move *scan_code* into *to_state*. Validates the transition is legal from
    the current state, atomically updates inventory_state, and appends an
    event to inventory_state_events.

    Raises ValueError on illegal transition or unknown to_state.
    """
    if not scan_code:
        raise ValueError("scan_code is required")
    if to_state not in STATES:
        raise ValueError(f"Unknown to_state {to_state!r}. Allowed: {sorted(STATES)}")

    now = _now()
    with _lock, _connect() as con:
        prev = con.execute(
            "SELECT * FROM inventory_state WHERE scan_code=?",
            (scan_code,),
        ).fetchone()
        from_state = prev["state"] if prev else None

        legal = LEGAL_TRANSITIONS.get(from_state, frozenset())
        if to_state not in legal:
            raise ValueError(
                f"Illegal transition for {scan_code!r}: "
                f"{from_state!r} → {to_state!r}. "
                f"Legal next states from {from_state!r}: {sorted(legal)}"
            )

        eff_trigger = trigger or DEFAULT_TRIGGER.get((from_state, to_state), "")

        if prev:
            con.execute(
                """UPDATE inventory_state SET
                       state=?, updated_at=?, updated_by=?, note=?,
                       product_code = CASE WHEN ?='' THEN product_code ELSE ? END,
                       design_no    = CASE WHEN ?='' THEN design_no    ELSE ? END,
                       batch_id     = CASE WHEN ?='' THEN batch_id     ELSE ? END
                   WHERE id=?""",
                (to_state, now, operator, note,
                 product_code, product_code,
                 design_no,    design_no,
                 batch_id,     batch_id,
                 prev["id"]),
            )
            row_id = prev["id"]
        else:
            row_id = str(uuid.uuid4())
            con.execute(
                """INSERT INTO inventory_state
                       (id, scan_code, product_code, design_no, batch_id,
                        state, updated_at, updated_by, note)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (row_id, scan_code, product_code, design_no, batch_id,
                 to_state, now, operator, note),
            )

        con.execute(
            """INSERT INTO inventory_state_events
                   (id, scan_code, from_state, to_state, trigger,
                    occurred_at, operator, note)
               VALUES (?,?,?,?,?,?,?,?)""",
            (str(uuid.uuid4()), scan_code, from_state or "", to_state,
             eff_trigger, now, operator, note),
        )

        row = con.execute(
            "SELECT * FROM inventory_state WHERE id=?", (row_id,),
        ).fetchone()
    return dict(row)
