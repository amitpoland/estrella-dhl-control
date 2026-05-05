"""
warehouse_audit.py — Read-only gap detection between packing_lines and warehouse scans.

Five checks, all read-only, no side effects, no schema changes:

  get_missing_scans(batch_id)
      Packing items that have never been scanned into the warehouse.

  get_stuck_inventory(batch_id, threshold_hours=24)
      Items still sitting at a RECV* location past a time threshold.

  get_invalid_flows(batch_id)
      Scan sequences that violate expected ordering:
        - DISPATCH or MOVE without a prior RECEIVE
        - RETURN without a prior DISPATCH

  get_orphan_inventory(batch_id)
      Warehouse records whose scan_code matches no packing line.

  get_batch_completion(batch_id)
      Counts and percentage: total / scanned / dispatched / missing.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from ..core.logging import get_logger
from . import packing_db as pdb
from . import warehouse_db as wdb

log = get_logger(__name__)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _ready() -> bool:
    return wdb._db_path is not None and pdb._db_path is not None


def _wcon() -> sqlite3.Connection:
    con = sqlite3.connect(str(wdb._db_path), check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


# ── 1. Missing scans ──────────────────────────────────────────────────────────

def get_missing_scans(batch_id: str) -> List[Dict[str, Any]]:
    """
    Return packing lines for *batch_id* that have never been scanned.

    A line is considered missing when its computed scan_code does not appear in
    inventory_current_location. Lines without a computable scan_code are skipped.
    """
    if not _ready() or not batch_id:
        return []

    packing_rows = pdb.get_packing_lines_for_batch(batch_id)
    if not packing_rows:
        return []

    # Collect all scan_codes already in the warehouse for this batch
    with _wcon() as con:
        wrows = con.execute(
            "SELECT scan_code FROM inventory_current_location WHERE batch_id=?",
            (batch_id,),
        ).fetchall()
    scanned: set[str] = {r["scan_code"] for r in wrows}

    missing = []
    for pl in packing_rows:
        sc = pl.get("scan_code") or wdb.scan_code_for_packing_line(pl)
        if sc and sc not in scanned:
            missing.append({**pl, "_expected_scan_code": sc})

    return missing


# ── 2. Stuck at RECV ──────────────────────────────────────────────────────────

def get_stuck_inventory(
    batch_id: str,
    threshold_hours: int = 24,
) -> List[Dict[str, Any]]:
    """
    Return items still at a RECV* location whose last movement is older than
    *threshold_hours*.  An item is "stuck" when it was received but never moved.
    """
    if not _ready() or not batch_id:
        return []

    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=threshold_hours)
    ).isoformat()

    with _wcon() as con:
        rows = con.execute(
            """SELECT * FROM inventory_current_location
               WHERE batch_id=?
                 AND (   current_location LIKE 'RECV%'
                      OR current_location LIKE 'recv%'
                      OR current_location LIKE '%/RECV%'
                      OR current_location LIKE '%/recv%')
                 AND updated_at < ?
               ORDER BY updated_at""",
            (batch_id, cutoff),
        ).fetchall()

    result = []
    for r in rows:
        d = dict(r)
        d["_stuck_hours"] = _hours_ago(d["updated_at"])
        result.append(d)
    return result


def _hours_ago(iso_ts: str) -> Optional[float]:
    try:
        dt = datetime.fromisoformat(iso_ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        return round(delta.total_seconds() / 3600, 1)
    except Exception:
        return None


# ── 3. Invalid flows ──────────────────────────────────────────────────────────

def get_invalid_flows(batch_id: str) -> List[Dict[str, Any]]:
    """
    Detect scan sequences that violate expected ordering for a batch.

    Violations reported:
      DISPATCH_WITHOUT_RECEIVE  — item dispatched before a RECEIVE scan
      MOVE_WITHOUT_RECEIVE      — item moved before a RECEIVE scan
      RETURN_WITHOUT_DISPATCH   — item returned without having been dispatched
    """
    if not _ready() or not batch_id:
        return []

    with _wcon() as con:
        rows = con.execute(
            """SELECT scan_code, action, event_time
               FROM inventory_movement_events
               WHERE batch_id=?
               ORDER BY scan_code, event_time""",
            (batch_id,),
        ).fetchall()

    # Group events by scan_code preserving order
    events_by_sc: Dict[str, List[Dict]] = {}
    for r in rows:
        sc = r["scan_code"]
        events_by_sc.setdefault(sc, []).append(dict(r))

    violations = []
    for sc, evts in events_by_sc.items():
        actions    = [e["action"] for e in evts]
        has_recv   = "RECEIVE" in actions
        has_disp   = "DISPATCH" in actions
        first_time = evts[0]["event_time"]

        # DISPATCH or MOVE without a prior RECEIVE
        if not has_recv:
            if "DISPATCH" in actions:
                violations.append({
                    "scan_code":        sc,
                    "violation":        "DISPATCH_WITHOUT_RECEIVE",
                    "actions_observed": actions,
                    "first_event_time": first_time,
                })
            elif any(a in actions for a in ("MOVE", "PICK", "PACK")):
                violations.append({
                    "scan_code":        sc,
                    "violation":        "MOVE_WITHOUT_RECEIVE",
                    "actions_observed": actions,
                    "first_event_time": first_time,
                })

        # RETURN without a prior DISPATCH
        if "RETURN" in actions and not has_disp:
            violations.append({
                "scan_code":        sc,
                "violation":        "RETURN_WITHOUT_DISPATCH",
                "actions_observed": actions,
                "first_event_time": first_time,
            })

    return violations


# ── 4. Orphan inventory ───────────────────────────────────────────────────────

def get_orphan_inventory(batch_id: str) -> List[Dict[str, Any]]:
    """
    Return inventory_current_location rows for *batch_id* whose scan_code
    cannot be matched to any packing line.

    An orphan means something was scanned that the shipment data does not know
    about — wrong barcode, wrong batch, data entry error.
    """
    if not _ready() or not batch_id:
        return []

    # Build the set of valid scan_codes from packing
    packing_rows = pdb.get_packing_lines_for_batch(batch_id)
    known: set[str] = set()
    for pl in packing_rows:
        sc = pl.get("scan_code") or wdb.scan_code_for_packing_line(pl)
        if sc:
            known.add(sc)

    # Compare against warehouse records for this batch
    with _wcon() as con:
        rows = con.execute(
            "SELECT * FROM inventory_current_location WHERE batch_id=?",
            (batch_id,),
        ).fetchall()

    return [dict(r) for r in rows if r["scan_code"] not in known]


# ── 5. Batch completion ───────────────────────────────────────────────────────

def get_batch_completion(batch_id: str) -> Dict[str, Any]:
    """
    Return completion statistics for a batch:
      total_items       — rows in packing_lines
      scanned_items     — rows in inventory_current_location
      dispatched_items  — rows with current_status='dispatched'
      missing_items     — total - scanned
      completion_pct    — scanned / total × 100
    """
    if not _ready() or not batch_id:
        return _empty_completion(batch_id)

    total = len(pdb.get_packing_lines_for_batch(batch_id))

    with _wcon() as con:
        scanned = con.execute(
            "SELECT COUNT(*) FROM inventory_current_location WHERE batch_id=?",
            (batch_id,),
        ).fetchone()[0]

        dispatched = con.execute(
            """SELECT COUNT(*) FROM inventory_current_location
               WHERE batch_id=? AND current_status='dispatched'""",
            (batch_id,),
        ).fetchone()[0]

    missing        = max(total - scanned, 0)
    completion_pct = round(scanned / total * 100, 1) if total > 0 else 0.0

    return {
        "batch_id":       batch_id,
        "total_items":    total,
        "scanned_items":  scanned,
        "dispatched_items": dispatched,
        "missing_items":  missing,
        "completion_pct": completion_pct,
    }


def _empty_completion(batch_id: str) -> Dict[str, Any]:
    return {
        "batch_id":         batch_id,
        "total_items":      0,
        "scanned_items":    0,
        "dispatched_items": 0,
        "missing_items":    0,
        "completion_pct":   0.0,
    }
