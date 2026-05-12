"""
inventory_state_engine.py — Lifecycle state model for PZ inventory.

Tracks each scannable item through its commercial lifecycle, independent of
physical-location tracking in warehouse_db.

States
------
  PURCHASE_TRANSIT       PZ generated, goods on the way from supplier
  WAREHOUSE_STOCK        Goods received at warehouse
  DIRECT_DISPATCH_READY  Goods cleared customs and operator marked them for
                         direct DHL/agency-to-client dispatch — never enter
                         the warehouse stock pool. Eligible for Proforma
                         issuance with the same protections as WAREHOUSE_STOCK.
  CLIENT_DISPATCHED      Direct-dispatch goods physically handed to carrier
                         for delivery to client. Eligible for late Proforma
                         issuance (some clients receive paperwork after
                         arrival).
  SALES_TRANSIT          Sales invoice issued, goods on the way to customer
  CLOSED                 Delivery confirmed, sale complete (terminal)

Transitions (only these are legal; everything else raises)
----------
  None                    → PURCHASE_TRANSIT       trigger: pz_generated
  PURCHASE_TRANSIT        → WAREHOUSE_STOCK        trigger: warehouse_receive
  PURCHASE_TRANSIT        → DIRECT_DISPATCH_READY  trigger: direct_dispatch_marked
                                                   (operator-explicit; evidence required)
  DIRECT_DISPATCH_READY   → CLIENT_DISPATCHED      trigger: client_dispatched
  WAREHOUSE_STOCK         → SALES_TRANSIT          trigger: invoice_issued
  SALES_TRANSIT           → CLOSED                 trigger: delivery_confirmed
  CLIENT_DISPATCHED       → CLOSED                 trigger: delivery_confirmed

Direct-dispatch evidence (enforced by transition() when to_state ==
DIRECT_DISPATCH_READY):
  - operator               must be non-empty
  - customer_allocation    client_name string, non-empty
  - customs_cleared        explicit True
  - movement event         a RECEIVE event must already exist for this
                           scan_code in inventory_movement_events (proves the
                           goods physically arrived, even if they bypass the
                           warehouse stock pool).

`RECEIVE` action on /api/v1/warehouse/scan does NOT auto-promote — lifecycle
state changes only via transition().

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

PURCHASE_TRANSIT       = "PURCHASE_TRANSIT"
WAREHOUSE_STOCK        = "WAREHOUSE_STOCK"
DIRECT_DISPATCH_READY  = "DIRECT_DISPATCH_READY"
CLIENT_DISPATCHED      = "CLIENT_DISPATCHED"
SALES_TRANSIT          = "SALES_TRANSIT"
CLOSED                 = "CLOSED"
# Phase B.1 — Sample-out lifecycle state. Piece is physically out at a
# client / trade show / quality check; must return to WAREHOUSE_STOCK.
# Explicitly NOT in PROFORMA_ELIGIBLE_STATES (see below).
SAMPLE_OUT             = "SAMPLE_OUT"

STATES: frozenset = frozenset({
    PURCHASE_TRANSIT, WAREHOUSE_STOCK,
    DIRECT_DISPATCH_READY, CLIENT_DISPATCHED,
    SALES_TRANSIT, CLOSED,
    SAMPLE_OUT,
})

# Sample-out reason enum (operator-provided per piece).
SAMPLE_OUT_REASONS: frozenset = frozenset({
    "customer_review",
    "quality_check",
    "marketing_photo",
    "trade_show",
    "other",
})

# Map: from_state (or None for first entry) → set of legal to_states.
LEGAL_TRANSITIONS: Dict[Optional[str], frozenset] = {
    None:                  frozenset({PURCHASE_TRANSIT}),
    PURCHASE_TRANSIT:      frozenset({WAREHOUSE_STOCK, DIRECT_DISPATCH_READY}),
    WAREHOUSE_STOCK:       frozenset({SALES_TRANSIT, SAMPLE_OUT}),
    DIRECT_DISPATCH_READY: frozenset({CLIENT_DISPATCHED}),
    CLIENT_DISPATCHED:     frozenset({CLOSED}),
    SALES_TRANSIT:         frozenset({CLOSED}),
    CLOSED:                frozenset(),
    # Sample-out can ONLY return to WAREHOUSE_STOCK. Forbidden by absence:
    # SAMPLE_OUT → CLOSED, SAMPLE_OUT → SALES_TRANSIT,
    # SAMPLE_OUT → CLIENT_DISPATCHED, SAMPLE_OUT → DIRECT_DISPATCH_READY,
    # SAMPLE_OUT → PURCHASE_TRANSIT, SAMPLE_OUT → SAMPLE_OUT (no double).
    SAMPLE_OUT:            frozenset({WAREHOUSE_STOCK}),
}

# Default trigger label for each transition; callers may override.
DEFAULT_TRIGGER: Dict[tuple, str] = {
    (None,                  PURCHASE_TRANSIT):      "pz_generated",
    (PURCHASE_TRANSIT,      WAREHOUSE_STOCK):       "warehouse_receive",
    (PURCHASE_TRANSIT,      DIRECT_DISPATCH_READY): "direct_dispatch_marked",
    (DIRECT_DISPATCH_READY, CLIENT_DISPATCHED):     "client_dispatched",
    (WAREHOUSE_STOCK,       SALES_TRANSIT):         "invoice_issued",
    (SALES_TRANSIT,         CLOSED):                "delivery_confirmed",
    (CLIENT_DISPATCHED,     CLOSED):                "delivery_confirmed",
    (WAREHOUSE_STOCK,       SAMPLE_OUT):            "sample_out_marked",
    (SAMPLE_OUT,            WAREHOUSE_STOCK):       "sample_returned",
}

# Lifecycle states that satisfy a Proforma stock-readiness gate.
# WAREHOUSE_STOCK         — classic warehoused goods.
# DIRECT_DISPATCH_READY   — customs-cleared, operator-marked for direct ship.
# CLIENT_DISPATCHED       — already dispatched directly to client.
PROFORMA_ELIGIBLE_STATES: frozenset = frozenset({
    WAREHOUSE_STOCK, DIRECT_DISPATCH_READY, CLIENT_DISPATCHED,
})

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


def _has_receive_event(con: sqlite3.Connection, scan_code: str) -> bool:
    """True iff a RECEIVE movement event exists for *scan_code*."""
    row = con.execute(
        "SELECT 1 FROM inventory_movement_events "
        "WHERE scan_code=? AND action='RECEIVE' LIMIT 1",
        (scan_code,),
    ).fetchone()
    return row is not None


def transition(
    *,
    scan_code:                str,
    to_state:                 str,
    trigger:                  Optional[str] = None,
    product_code:             str = "",
    design_no:                str = "",
    batch_id:                 str = "",
    operator:                 str = "",
    note:                     str = "",
    customer_allocation:      str = "",
    customs_cleared:          bool = False,
    # ── Sample-out evidence (only consulted when to_state == SAMPLE_OUT) ─
    recipient_client_name:    str = "",
    expected_return_date:     str = "",
    sample_reason:            str = "",
) -> Dict[str, Any]:
    """
    Move *scan_code* into *to_state*. Validates the transition is legal from
    the current state, atomically updates inventory_state, and appends an
    event to inventory_state_events.

    Raises ValueError on illegal transition, unknown to_state, or — for
    states that require evidence — missing/invalid evidence. Evidence
    contracts per to_state:

      DIRECT_DISPATCH_READY:
        - operator non-empty
        - customer_allocation non-empty
        - customs_cleared True
        - a RECEIVE movement event must already exist

      SAMPLE_OUT:
        - operator non-empty
        - recipient_client_name non-empty
        - sample_reason in SAMPLE_OUT_REASONS
        - expected_return_date ISO 8601 and in the future
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

        # Evidence gate — direct-dispatch is the only branch that bypasses the
        # warehouse stock pool, so we enforce a hard evidence contract here
        # rather than in callers (which can drift). Each missing piece raises
        # a distinct ValueError so the operator UI can show the exact gap.
        if to_state == DIRECT_DISPATCH_READY:
            missing: List[str] = []
            if not (operator or "").strip():
                missing.append("operator")
            if not (customer_allocation or "").strip():
                missing.append("customer_allocation")
            if not customs_cleared:
                missing.append("customs_cleared=True")
            if not _has_receive_event(con, scan_code):
                missing.append("RECEIVE movement event")
            if missing:
                raise ValueError(
                    f"DIRECT_DISPATCH_READY requires evidence; missing: "
                    f"{', '.join(missing)}"
                )

        # Evidence gate — Sample-out (Phase B.1). Forbids transition into
        # SAMPLE_OUT without operator + recipient + valid reason + future
        # expected return. Forbidden transitions (SAMPLE_OUT → anything
        # except WAREHOUSE_STOCK) are blocked by absence from
        # LEGAL_TRANSITIONS and rejected by the legality check above.
        if to_state == SAMPLE_OUT:
            missing = []
            if not (operator or "").strip():
                missing.append("operator")
            if not (recipient_client_name or "").strip():
                missing.append("recipient_client_name")
            if not (sample_reason or "").strip():
                missing.append("sample_reason")
            elif sample_reason not in SAMPLE_OUT_REASONS:
                missing.append(
                    f"sample_reason∈{sorted(SAMPLE_OUT_REASONS)} "
                    f"(got {sample_reason!r})"
                )
            if not (expected_return_date or "").strip():
                missing.append("expected_return_date")
            else:
                try:
                    erd_normalized = (
                        expected_return_date.replace("Z", "+00:00")
                        if expected_return_date.endswith("Z")
                        else expected_return_date
                    )
                    erd = datetime.fromisoformat(erd_normalized)
                    if erd.tzinfo is None:
                        erd = erd.replace(tzinfo=timezone.utc)
                    if erd <= datetime.now(timezone.utc):
                        missing.append("expected_return_date in the future")
                except (ValueError, TypeError):
                    missing.append(
                        f"expected_return_date ISO 8601 "
                        f"(got {expected_return_date!r})"
                    )
            if missing:
                raise ValueError(
                    f"SAMPLE_OUT requires evidence; missing: "
                    f"{', '.join(missing)}"
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
