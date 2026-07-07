"""
inventory_reconciliation_service.py — Inventory Intelligence, Phase 1 (READ-ONLY).

Consume-only reconciliation of the inventory authority against the purchase and
identity authorities. It answers, per batch: how many pieces are in inventory,
how many carry no product identity, how the scanned piece count compares to the
billed packing quantity, and how many inventory product codes are covered by the
Product Master — then rolls that into an advisory health status.

AUTHORITY / SAFETY CONTRACT (Inventory Intelligence Phase 1):
  * Inventory CONSUMES: inventory_state (warehouse.db), packing_lines (packing.db),
    product_master (reservation_queue.db, ADVISORY only).
  * Inventory NEVER writes upward. This module issues SELECT only, opens every DB
    with ``PRAGMA query_only=ON`` (a hard runtime write-block), and never creates a
    DB file (missing file → empty result, never an implicit write).
  * Product Master coverage is ADVISORY (Lesson N): it is reported but NEVER drives
    the health status and NEVER blocks anything.

No schema change, no new authority, no state transition, no repair. Read + report.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# ── health model ─────────────────────────────────────────────────────────────
# Advisory thresholds. Product Master coverage is deliberately NOT a health input.
#   critical : over_scan > 0 (more pieces than billed) OR blank product_code > 0
#              (unidentified stock) — genuine data-integrity signals.
#   warning  : under_scan > 0 (billed qty not fully scanned) — operational, not
#              an integrity breach.
#   healthy  : none of the above.
HEALTH_HEALTHY = "healthy"
HEALTH_WARNING = "warning"
HEALTH_CRITICAL = "critical"
_HEALTH_ORDER = {HEALTH_CRITICAL: 0, HEALTH_WARNING: 1, HEALTH_HEALTHY: 2}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _num(v: float):
    """Render a float as an int when it is whole (e.g. 3.0 → 3), else rounded."""
    f = round(float(v), 3)
    return int(f) if f == int(f) else f


def _ro_connect(path: Optional[Path]) -> Optional[sqlite3.Connection]:
    """Open a READ-ONLY connection.

    Returns None when the DB file is absent — critically, we never let
    sqlite3.connect() create the file (that would be an implicit write against an
    authority we only consume). ``PRAGMA query_only=ON`` hard-blocks any write on
    the connection even if a future bug tried one.
    """
    if path is None:
        return None
    p = Path(path)
    if not p.exists():
        return None
    con = sqlite3.connect(str(p))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    return con


def _read_rows(path: Optional[Path], sql: str) -> List[Dict[str, Any]]:
    con = _ro_connect(path)
    if con is None:
        return []
    try:
        rows = con.execute(sql).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError:
        # Missing table / older schema → degrade to empty, never fail the report.
        return []
    finally:
        con.close()


def _master_codes(path: Optional[Path]) -> Set[str]:
    codes: Set[str] = set()
    for r in _read_rows(path, "SELECT product_code FROM product_master"):
        pc = (r.get("product_code") or "").strip()
        if pc:
            codes.add(pc)
    return codes


def _health(blank_pc: int, under_scan: float, over_scan: float) -> Tuple[str, List[str]]:
    reasons: List[str] = []
    if over_scan > 0:
        reasons.append(f"over_scan={_num(over_scan)}: inventory pieces exceed billed packing quantity")
    if blank_pc > 0:
        reasons.append(f"blank_product_code={blank_pc}: pieces in inventory carry no product identity")
    if under_scan > 0:
        reasons.append(f"under_scan={_num(under_scan)}: billed packing quantity not fully scanned into stock")
    if over_scan > 0 or blank_pc > 0:
        return HEALTH_CRITICAL, reasons
    if under_scan > 0:
        return HEALTH_WARNING, reasons
    return HEALTH_HEALTHY, reasons


def compute_reconciliation(
    *,
    warehouse_db_path: Optional[Path],
    packing_db_path: Optional[Path],
    reservation_db_path: Optional[Path],
) -> Dict[str, Any]:
    """Pure read-only reconciliation. All three inputs are DB file paths; any that
    are missing simply contribute nothing (never an error, never a write)."""
    inv = _read_rows(warehouse_db_path, "SELECT batch_id, product_code, state FROM inventory_state")
    pak = _read_rows(packing_db_path, "SELECT batch_id, product_code, quantity FROM packing_lines")
    master = _master_codes(reservation_db_path)

    # Aggregate per batch (union of inventory and packing batches).
    agg: Dict[str, Dict[str, Any]] = {}

    def _bucket(bid: str) -> Dict[str, Any]:
        return agg.setdefault(bid, {
            "inv_pieces": 0,
            "blank_pc": 0,
            "inv_codes": set(),
            "pack_qty": 0.0,
            "state_breakdown": {},
        })

    for r in inv:
        b = _bucket(r.get("batch_id") or "")
        b["inv_pieces"] += 1
        pc = (r.get("product_code") or "").strip()
        if pc:
            b["inv_codes"].add(pc)
        else:
            b["blank_pc"] += 1
        st = r.get("state") or ""
        b["state_breakdown"][st] = b["state_breakdown"].get(st, 0) + 1

    for r in pak:
        b = _bucket(r.get("batch_id") or "")
        try:
            b["pack_qty"] += float(r.get("quantity") or 0)
        except (TypeError, ValueError):
            pass

    batches: List[Dict[str, Any]] = []
    totals = {
        "total_inventory_pieces": 0,
        "blank_product_code_pieces": 0,
        "packing_quantity": 0.0,
        "inventory_quantity": 0,
        "under_scan": 0.0,
        "over_scan": 0.0,
        "product_master_coverage_count": 0,
        "product_master_missing_count": 0,
        "health": {HEALTH_HEALTHY: 0, HEALTH_WARNING: 0, HEALTH_CRITICAL: 0},
    }

    for bid in sorted(agg):
        b = agg[bid]
        pack_qty = round(b["pack_qty"], 3)
        inv_qty = b["inv_pieces"]
        under = round(max(0.0, pack_qty - inv_qty), 3)
        over = round(max(0.0, inv_qty - pack_qty), 3)
        coverage = len(b["inv_codes"] & master)
        missing = len(b["inv_codes"] - master)
        health, reasons = _health(b["blank_pc"], under, over)

        batches.append({
            "batch_id": bid,
            "total_inventory_pieces": b["inv_pieces"],
            "blank_product_code_pieces": b["blank_pc"],
            "packing_quantity": _num(pack_qty),
            "inventory_quantity": inv_qty,
            "under_scan": _num(under),
            "over_scan": _num(over),
            "product_master_coverage_count": coverage,
            "product_master_missing_count": missing,
            "state_breakdown": dict(sorted(b["state_breakdown"].items())),
            "health_status": health,
            "health_reasons": reasons,
        })

        totals["total_inventory_pieces"] += b["inv_pieces"]
        totals["blank_product_code_pieces"] += b["blank_pc"]
        totals["packing_quantity"] += pack_qty
        totals["inventory_quantity"] += inv_qty
        totals["under_scan"] += under
        totals["over_scan"] += over
        totals["product_master_coverage_count"] += coverage
        totals["product_master_missing_count"] += missing
        totals["health"][health] += 1

    totals["packing_quantity"] = _num(totals["packing_quantity"])
    totals["under_scan"] = _num(totals["under_scan"])
    totals["over_scan"] = _num(totals["over_scan"])

    # Severity-first ordering so the worst batches surface at the top.
    batches.sort(key=lambda x: (_HEALTH_ORDER.get(x["health_status"], 9), x["batch_id"]))

    return {
        "generated_at": _now_iso(),
        "batch_count": len(batches),
        "totals": totals,
        "batches": batches,
    }


def run_reconciliation() -> Dict[str, Any]:
    """Production entry point — resolves the configured authority DB paths and runs
    the read-only reconciliation. Uses the already-initialised module DB paths
    (warehouse_db / packing_db) and the standard reservation_queue.db location."""
    from . import warehouse_db, packing_db
    from ..core.config import settings

    reservation_path = Path(settings.storage_root) / "reservation_queue.db"
    return compute_reconciliation(
        warehouse_db_path=warehouse_db._db_path,
        packing_db_path=packing_db._db_path,
        reservation_db_path=reservation_path,
    )
