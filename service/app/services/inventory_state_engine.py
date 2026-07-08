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

# Phase B.2 — Returns lifecycle states. Two physical-custody classes:
#   RETURNED_FROM_CLIENT: piece is physically in the warehouse RMA
#     area, awaiting QA / regrade / restock / escalation.
#   RETURNED_TO_PRODUCER: piece is physically with the producer for
#     rework / replacement / settlement.
# Neither is in PROFORMA_ELIGIBLE_STATES (see below).
RETURNED_FROM_CLIENT   = "RETURNED_FROM_CLIENT"
RETURNED_TO_PRODUCER   = "RETURNED_TO_PRODUCER"

# Returns QC Disposition — terminal write-off state. A client-returned piece
# that QC decides to scrap is retired here (RETURNED_FROM_CLIENT → WRITTEN_OFF).
# Terminal like CLOSED — never reopens. This is the "separate, scoped flow" the
# RETURNED_FROM_CLIENT → CLOSED comment (design §4) deferred; write-off is an
# inventory disposition only and carries NO accounting/wFirma side effect.
WRITTEN_OFF            = "WRITTEN_OFF"

STATES: frozenset = frozenset({
    PURCHASE_TRANSIT, WAREHOUSE_STOCK,
    DIRECT_DISPATCH_READY, CLIENT_DISPATCHED,
    SALES_TRANSIT, CLOSED,
    SAMPLE_OUT,
    RETURNED_FROM_CLIENT, RETURNED_TO_PRODUCER,
    WRITTEN_OFF,
})

# ── C13A — Read-only PURCHASE_TRANSIT projection ────────────────────────────
#
# A batch with goods in DHL/customs flight but not yet warehouse-scanned has
# zero rows in `inventory_state`.  Without a projection the dashboard reports
# the shipment as "missing inventory" — operationally misleading, since the
# goods are tracked, declared, and on their way.  C13A adds a READ-ONLY
# synthetic projection that surfaces these scan_codes with state
# PURCHASE_TRANSIT, derived from audit.clearance_status + packing lines.
#
# Invariants enforced by this design:
#   1.  Never writes to `inventory_state`.  The write path remains the
#       transition() engine alone; synthetic rows live only in API responses.
#   2.  Real rows always win.  Callers consult the projection only when
#       inventory_state has zero rows for the batch.
#   3.  Closed / delivered-and-received / archived shipments never produce
#       a synthetic projection, even with zero scan rows — the operator
#       must investigate, not be told the goods are "in transit".
#   4.  Synthetic rows carry `"synthetic": True` and
#       `"source": "audit.tracking"` so downstream consumers can distinguish
#       provenance.

# clearance_status values that mean "DHL/customs flight is active".
# Mirrors routes_proforma._LIFECYCLE_TRANSIT_STATUSES (C12).
_LIFECYCLE_TRANSIT_STATUSES: frozenset = frozenset({
    "classified",
    "in_transit",
    "dsk_generated",
    "dsk_transfer_queued",
    "dsk_transfer_sent",
    "agency_email_queued",
    "dsk_sent",
    "reply_queued",
    "reply_sent",
})

# clearance_status values that mean "the shipment is no longer in transit".
# Synthetic projection is suppressed for these — the operator must explain
# why scans are missing if the batch is closed.
_LIFECYCLE_TERMINAL_STATUSES: frozenset = frozenset({
    "pz_generated",
    "closed",
    "delivered_and_received",
    "archived",
    "cancelled",
})


def derive_purchase_transit_projection(
    batch_id: str,
    audit: Optional[Dict[str, Any]],
    packing_lines: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """READ-ONLY synthetic PURCHASE_TRANSIT projection.

    Returns a list of synthetic per-scan_code rows when:
      - ``audit`` is present and ``clearance_status`` is in the
        transit set (and NOT in the terminal set), AND
      - at least one packing line exists for the batch.

    Returns an empty list otherwise.

    DOES NOT WRITE anything to `inventory_state`.  The synthetic rows are
    produced from the packing list (the only honest evidence we have about
    what is on the shipment) and tagged so callers can never confuse them
    with real scan-in records.

    Each returned row has the same shape as
    ``inventory_batch_state._list_pieces_for_batch`` (scan_code, state,
    product_code, design_no, updated_at) plus two extra keys:

        ``synthetic`` = True
        ``source``    = "audit.tracking"
    """
    if not batch_id or not isinstance(audit, dict):
        return []
    if not isinstance(packing_lines, list) or not packing_lines:
        return []

    status = (audit.get("clearance_status") or "").strip().lower()
    if not status:
        return []
    if status in _LIFECYCLE_TERMINAL_STATUSES:
        return []
    if status not in _LIFECYCLE_TRANSIT_STATUSES:
        return []

    # Updated-at timestamp: prefer audit.tracking.last_update, else now.
    updated_at = ""
    trk = audit.get("tracking")
    if isinstance(trk, dict):
        updated_at = (trk.get("last_update") or "").strip() or ""
    if not updated_at:
        updated_at = _now()

    out: List[Dict[str, Any]] = []
    seen: set = set()
    for ln in packing_lines:
        if not isinstance(ln, dict):
            continue
        scan = (ln.get("scan_code") or "").strip()
        if not scan or scan in seen:
            continue
        seen.add(scan)
        # C13E: expand by quantity so each logical unit gets its own synthetic
        # row.  packing_lines.quantity already contains normalised units (PRS
        # earring pairs are already counted correctly by the parser).
        qty = _coerce_qty(ln.get("quantity"))
        product_code = (ln.get("product_code") or "").strip() or None
        design_no    = (ln.get("design_no")    or "").strip() or None
        for i in range(1, qty + 1):
            expanded_scan = scan if qty == 1 else f"{scan}#{i}"
            out.append({
                "scan_code":    expanded_scan,
                "state":        PURCHASE_TRANSIT,
                "product_code": product_code,
                "design_no":    design_no,
                "updated_at":   updated_at,
                "synthetic":    True,
                "source":       "audit.tracking",
            })
    return out


def _coerce_qty(raw) -> int:
    """Coerce a packing-line quantity to a positive integer (>= 1).

    Handles: None → 1, float strings → int(float()), <= 0 → 1, non-numeric → 1.
    packing_db stores quantity as REAL so "2.0" and 2.0 must both work.
    """
    if raw is None:
        return 1
    try:
        v = int(float(str(raw)))
        return v if v > 0 else 1
    except (ValueError, TypeError):
        return 1

# Sample-out reason enum (operator-provided per piece).
SAMPLE_OUT_REASONS: frozenset = frozenset({
    "customer_review",
    "quality_check",
    "marketing_photo",
    "trade_show",
    "other",
})

# Returns reason enums (operator-provided per piece). Distinct enum
# per direction so the UI can show only the relevant reasons.
RETURNED_FROM_CLIENT_REASONS: frozenset = frozenset({
    "warranty_claim",
    "customer_refused",
    "post_sample_review_reject",
    "dimension_issue",
    "quality_complaint",
    "wrong_item_shipped",
    "other",
})
RETURNED_TO_PRODUCER_REASONS: frozenset = frozenset({
    "defect",
    "dimension_out_of_spec",
    "quality_reject",
    "post_inspection_reject",
    "recall",
    "other",
})

# Map: from_state (or None for first entry) → set of legal to_states.
LEGAL_TRANSITIONS: Dict[Optional[str], frozenset] = {
    None:                  frozenset({PURCHASE_TRANSIT}),
    PURCHASE_TRANSIT:      frozenset({WAREHOUSE_STOCK, DIRECT_DISPATCH_READY}),
    # Phase B.2 — RETURNED_FROM_CLIENT becomes a legal successor of
    # WAREHOUSE_STOCK so a piece sitting in warehouse that is later
    # identified as defective/returned-RMA can be logged without an
    # outbound first. Also legal: RETURNED_TO_PRODUCER from warehouse
    # for defective stock found in the warehouse.
    WAREHOUSE_STOCK:       frozenset({SALES_TRANSIT, SAMPLE_OUT,
                                      RETURNED_FROM_CLIENT,
                                      RETURNED_TO_PRODUCER}),
    DIRECT_DISPATCH_READY: frozenset({CLIENT_DISPATCHED}),
    CLIENT_DISPATCHED:     frozenset({CLOSED}),
    SALES_TRANSIT:         frozenset({CLOSED}),
    # CLOSED stays terminal. Resolved 2026-05-12 in
    # RETURNS_LIFECYCLE_DESIGN.md §2: producer replacements use a
    # new scan_code rather than a CLOSED → anything transition.
    CLOSED:                frozenset(),
    # Sample-out can now also escalate into RETURNED_FROM_CLIENT
    # (sample came back with a problem). Forbidden by absence:
    # SAMPLE_OUT → CLOSED, SAMPLE_OUT → SALES_TRANSIT,
    # SAMPLE_OUT → CLIENT_DISPATCHED, SAMPLE_OUT → DIRECT_DISPATCH_READY,
    # SAMPLE_OUT → PURCHASE_TRANSIT, SAMPLE_OUT → SAMPLE_OUT,
    # SAMPLE_OUT → RETURNED_TO_PRODUCER (must go through RMA first).
    SAMPLE_OUT:            frozenset({WAREHOUSE_STOCK, RETURNED_FROM_CLIENT}),
    # Phase B.2 — Returns successors. Forbidden by absence is rich
    # here (see RETURNS_LIFECYCLE_DESIGN.md §4 for the full list):
    #   * RETURNED_FROM_CLIENT cannot become SAMPLE_OUT / SALES_TRANSIT /
    #     CLIENT_DISPATCHED / DIRECT_DISPATCH_READY / PURCHASE_TRANSIT.
    #   * RETURNED_FROM_CLIENT → CLOSED stays forbidden (CLOSED is the
    #     sales-delivery terminal). The scoped write-off flow retires a
    #     client-returned piece via RETURNED_FROM_CLIENT → WRITTEN_OFF
    #     instead (Returns QC Disposition), keeping CLOSED semantics clean.
    #   * RETURNED_TO_PRODUCER cannot become SAMPLE_OUT / SALES_TRANSIT /
    #     CLIENT_DISPATCHED / DIRECT_DISPATCH_READY / PURCHASE_TRANSIT.
    #   * RETURNED_TO_PRODUCER → CLOSED is forbidden (CLOSED terminal
    #     rule, §2 of design). Settlement that retires a scan_code
    #     uses a new scan_code; this state does not retire.
    RETURNED_FROM_CLIENT:  frozenset({WAREHOUSE_STOCK, RETURNED_TO_PRODUCER,
                                      WRITTEN_OFF}),
    RETURNED_TO_PRODUCER:  frozenset({WAREHOUSE_STOCK, RETURNED_FROM_CLIENT}),
    # WRITTEN_OFF is terminal — a scrapped piece never reopens (mirrors CLOSED).
    WRITTEN_OFF:           frozenset(),
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
    # Phase B.2 — Returns triggers.
    (WAREHOUSE_STOCK,       RETURNED_FROM_CLIENT):  "returned_from_client_received",
    (SAMPLE_OUT,            RETURNED_FROM_CLIENT):  "returned_from_client_received",
    (WAREHOUSE_STOCK,       RETURNED_TO_PRODUCER):  "returned_to_producer_shipped",
    (RETURNED_FROM_CLIENT,  WAREHOUSE_STOCK):       "returned_restocked",
    (RETURNED_FROM_CLIENT,  RETURNED_TO_PRODUCER):  "returned_escalated_to_producer",
    (RETURNED_FROM_CLIENT,  WRITTEN_OFF):           "qc_written_off",
    (RETURNED_TO_PRODUCER,  WAREHOUSE_STOCK):       "returned_from_producer_restocked",
    (RETURNED_TO_PRODUCER,  RETURNED_FROM_CLIENT):  "returned_from_producer_to_rma",
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


def list_all_states_for_batch(batch_id: str) -> Dict[str, List[str]]:
    """Return {state: [scan_code, ...]} for all states in a single SQL query.

    Replaces the previous pattern of calling list_by_state() once per state
    (9 round-trips → 1 round-trip).  Returns an empty dict on any error so
    callers degrade gracefully rather than failing a preview.
    """
    if not batch_id:
        return {}
    try:
        with _connect() as con:
            rows = con.execute(
                "SELECT state, scan_code FROM inventory_state WHERE batch_id=?",
                (batch_id,),
            ).fetchall()
    except Exception:
        return {}
    out: Dict[str, List[str]] = {}
    for r in rows:
        s = r["state"]
        if s in STATES:
            out.setdefault(s, []).append(r["scan_code"])
    return out


def list_events_for_batch(batch_id: str, limit: int = 1000) -> List[Dict[str, Any]]:
    """Append-only lifecycle event trail for every piece of *batch_id*,
    newest first. Read-only (C-3f — movement/document-trail reads; the
    engine owns its event table, so the batch reader lives here).
    Returns [] on any error so read surfaces degrade gracefully."""
    if not batch_id:
        return []
    limit = max(1, min(int(limit or 1000), 5000))
    try:
        with _connect() as con:
            rows = con.execute(
                """SELECT e.* FROM inventory_state_events e
                   JOIN inventory_state s ON s.scan_code = e.scan_code
                   WHERE s.batch_id = ?
                   ORDER BY e.occurred_at DESC
                   LIMIT ?""",
                (batch_id, limit),
            ).fetchall()
    except Exception:
        return []
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


def correct_identity(
    *,
    scan_code:    str,
    operator:     str,
    product_code: Optional[str] = None,
    design_no:    Optional[str] = None,
    batch_id:     Optional[str] = None,
) -> Dict[str, Any]:
    """Correct product_code / design_no / batch_id on an existing inventory_state
    row WITHOUT changing lifecycle state.

    This is deliberately separate from transition(): LEGAL_TRANSITIONS has no
    entry mapping any state to itself, so an identity fix cannot be expressed
    as a transition. It never writes inventory_state_events — that table is
    the lifecycle-transition audit trail; the append-only inventory_corrections
    table (see inventory_correction_writer.py) is the audit trail for identity
    fixes.

    Pass None for a field to leave it unchanged; pass "" explicitly to clear
    it. At least one of product_code/design_no/batch_id must be provided (not
    None). Raises ValueError if scan_code is unknown or no field is given.
    """
    if not scan_code:
        raise ValueError("scan_code is required")
    if not operator:
        raise ValueError("operator is required (session-derived)")
    if product_code is None and design_no is None and batch_id is None:
        raise ValueError("at least one of product_code/design_no/batch_id is required")

    now = _now()
    with _lock, _connect() as con:
        prev = con.execute(
            "SELECT * FROM inventory_state WHERE scan_code=?", (scan_code,)
        ).fetchone()
        if prev is None:
            raise ValueError(f"scan_code {scan_code!r} not found in inventory_state")

        new_product_code = prev["product_code"] if product_code is None else product_code
        new_design_no    = prev["design_no"]    if design_no    is None else design_no
        new_batch_id     = prev["batch_id"]     if batch_id     is None else batch_id

        con.execute(
            """UPDATE inventory_state
               SET product_code=?, design_no=?, batch_id=?, updated_at=?, updated_by=?
               WHERE id=?""",
            (new_product_code, new_design_no, new_batch_id, now, operator, prev["id"]),
        )
        row = con.execute(
            "SELECT * FROM inventory_state WHERE id=?", (prev["id"],)
        ).fetchone()
    return dict(row)


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
    # ── Returns evidence (Phase B.2, only consulted when
    #    to_state == RETURNED_FROM_CLIENT or RETURNED_TO_PRODUCER) ─
    return_reason:            str = "",
    source_holder_name:       str = "",   # who returned the piece (RFC)
    producer_name:            str = "",   # producer claim target (RTP)
    received_at:              str = "",   # ISO 8601, not in future (RFC)
    expected_resolution_date: str = "",   # ISO 8601 optional (RTP)
    dispatch_reference:       str = "",   # outbound waybill / RMA (RTP)
    origin_context:           str = "",   # free-text origin-link note (RFC)
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

        # Evidence gate — RETURNED_FROM_CLIENT (Phase B.2). Inbound
        # receipt: operator + reason + origin_context + received_at
        # in the past or present (inverse of SAMPLE_OUT's future-date
        # rule). RETURNS_LIFECYCLE_DESIGN.md §5.1.
        if to_state == RETURNED_FROM_CLIENT:
            missing = []
            if not (operator or "").strip():
                missing.append("operator")
            if not (return_reason or "").strip():
                missing.append("return_reason")
            elif return_reason not in RETURNED_FROM_CLIENT_REASONS:
                missing.append(
                    f"return_reason∈{sorted(RETURNED_FROM_CLIENT_REASONS)} "
                    f"(got {return_reason!r})"
                )
            if not (origin_context or "").strip():
                missing.append("origin_context")
            if not (received_at or "").strip():
                missing.append("received_at")
            else:
                try:
                    ra_normalized = (
                        received_at.replace("Z", "+00:00")
                        if received_at.endswith("Z")
                        else received_at
                    )
                    ra = datetime.fromisoformat(ra_normalized)
                    if ra.tzinfo is None:
                        ra = ra.replace(tzinfo=timezone.utc)
                    if ra > datetime.now(timezone.utc):
                        missing.append("received_at not in the future")
                except (ValueError, TypeError):
                    missing.append(
                        f"received_at ISO 8601 (got {received_at!r})"
                    )
            if missing:
                raise ValueError(
                    f"RETURNED_FROM_CLIENT requires evidence; missing: "
                    f"{', '.join(missing)}"
                )

        # Evidence gate — RETURNED_TO_PRODUCER (Phase B.2). Outbound
        # to producer: operator + producer_name + reason or dispatch
        # reference; expected_resolution_date optional but if given
        # must be ISO 8601 in the future. RETURNS_LIFECYCLE_DESIGN.md
        # §5.2.
        if to_state == RETURNED_TO_PRODUCER:
            missing = []
            if not (operator or "").strip():
                missing.append("operator")
            if not (producer_name or "").strip():
                missing.append("producer_name")
            # Either a structured reason OR a dispatch reference must
            # exist so the audit row is never empty. The brief permits
            # "dispatch_reference or reason"; we accept either.
            has_reason = bool((return_reason or "").strip())
            has_ref    = bool((dispatch_reference or "").strip())
            if not (has_reason or has_ref):
                missing.append("return_reason or dispatch_reference")
            elif has_reason and return_reason not in RETURNED_TO_PRODUCER_REASONS:
                missing.append(
                    f"return_reason∈{sorted(RETURNED_TO_PRODUCER_REASONS)} "
                    f"(got {return_reason!r})"
                )
            # expected_resolution_date is optional — only validate
            # format + future-ness when provided.
            if (expected_resolution_date or "").strip():
                try:
                    erd_normalized = (
                        expected_resolution_date.replace("Z", "+00:00")
                        if expected_resolution_date.endswith("Z")
                        else expected_resolution_date
                    )
                    erd = datetime.fromisoformat(erd_normalized)
                    if erd.tzinfo is None:
                        erd = erd.replace(tzinfo=timezone.utc)
                    if erd <= datetime.now(timezone.utc):
                        missing.append("expected_resolution_date in the future")
                except (ValueError, TypeError):
                    missing.append(
                        f"expected_resolution_date ISO 8601 "
                        f"(got {expected_resolution_date!r})"
                    )
            if missing:
                raise ValueError(
                    f"RETURNED_TO_PRODUCER requires evidence; missing: "
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
