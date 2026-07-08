"""
inventory_fiscal_reconciliation_service.py — WF-2 Inventory Reconciliation (READ-ONLY).

Compares the two constitutionally-separate inventory objects and REPORTS the
difference. It changes nothing on either side.

  Input A — Dashboard OPERATIONAL piece-stock (warehouse.db / inventory_state),
            on-hand = pieces in WAREHOUSE_STOCK (the Dashboard "final stock"
            definition; single source of truth via inventory_state_engine).
  Input B — wFirma FISCAL quantity (wfirma_fiscal_inventory.read_fiscal_inventory
            → goods/find filtered by warehouse_id).
  Output  — a classified, severity-ranked DIFFERENCE report. No writes, no fixes.

AUTHORITY / SAFETY (WF-1A Inventory Ownership Constitution):
  * Dashboard owns operational stock; wFirma owns fiscal quantity. These are
    different business objects; reconciliation owns NEITHER and overwrites
    NEITHER (WF-2 governance: read-only, single authority, no hidden sync).
  * This module issues SELECT only against inventory_state, opens it with
    ``PRAGMA query_only=ON`` (hard write-block), and never creates a DB file.
  * The fiscal side is consumed ONLY through the canonical reader
    (wfirma_fiscal_inventory); this module never calls wFirma or SQLs the mirror
    directly. The product↔wFirma link is read through the canonical Product
    mirror accessor (reservation_db.list_mirror_products).
  * When the fiscal side is unavailable, the report is honestly marked
    ``fiscal_source="unavailable"`` with NO invented differences.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, List, Optional, Set

from . import inventory_state_engine
from . import wfirma_fiscal_inventory
from . import reservation_db
from . import inventory_reconciliation_audit_db as audit_db

# On-hand = the Dashboard "STOCK UNITS (FINAL)" definition (WAREHOUSE_STOCK).
# Pieces in transit / sample / dispatched / returned-to-producer are physically
# absent from the warehouse and are intentionally NOT counted as fiscal on-hand;
# the per-product state breakdown is surfaced so any mismatch is explainable.
_ON_HAND_STATES: frozenset = frozenset({inventory_state_engine.WAREHOUSE_STOCK})

# ── severity model (business rules) ─────────────────────────────────────────
SEV_LOW = "LOW"
SEV_MEDIUM = "MEDIUM"
SEV_HIGH = "HIGH"
SEV_CRITICAL = "CRITICAL"
_SEV_ORDER = {SEV_CRITICAL: 0, SEV_HIGH: 1, SEV_MEDIUM: 2, SEV_LOW: 3}

# Absolute delta at/above which a quantity mismatch escalates from MEDIUM to HIGH.
_QTY_MISMATCH_HIGH_ABS = 5

# ── difference types ────────────────────────────────────────────────────────
T_MISSING_WFIRMA = "missing_in_wfirma"
T_MISSING_DASHBOARD = "missing_in_dashboard"
T_QTY_MISMATCH = "quantity_mismatch"
T_MAPPING_MISSING = "product_mapping_missing"
T_WAREHOUSE_MISMATCH = "warehouse_mismatch"
T_UNKNOWN_WAREHOUSE = "unknown_warehouse"
T_UNKNOWN_PRODUCT = "unknown_product"
T_DUPLICATE_PRODUCT = "duplicate_product"
T_DUPLICATE_MAPPING = "duplicate_mapping"

_RECOMMENDED_ACTION = {
    T_MISSING_WFIRMA: "Dashboard holds stock wFirma does not — verify the PZ is posted and the good exists in wFirma.",
    T_MISSING_DASHBOARD: "wFirma holds stock the Dashboard does not track — verify direct wFirma entry / warehouse scan-in.",
    T_QTY_MISMATCH: "Reconcile the counts — confirm postings/scans; no automatic correction is applied.",
    T_MAPPING_MISSING: "Map the product to wFirma via Product Master → mirror before it can be fiscally reconciled.",
    T_WAREHOUSE_MISMATCH: "Informational — this product's fiscal stock is split across multiple warehouses.",
    T_UNKNOWN_WAREHOUSE: "Verify the configured warehouse id exists in wFirma (warehouses/find).",
    T_UNKNOWN_PRODUCT: "wFirma good carries no product code — assign a code so it can be reconciled.",
    T_DUPLICATE_PRODUCT: "Duplicate wFirma good for one product code — deduplicate in wFirma.",
    T_DUPLICATE_MAPPING: "One product code maps to multiple wFirma ids — deduplicate the mirror mapping.",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── read-only operational reader ────────────────────────────────────────────

def _ro_connect(path: Optional[Path]) -> Optional[sqlite3.Connection]:
    """READ-ONLY connection; never creates the file, hard-blocks writes."""
    if path is None:
        return None
    p = Path(path)
    if not p.exists():
        return None
    con = sqlite3.connect(str(p))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    return con


def _read_operational(warehouse_db_path: Optional[Path]) -> Dict[str, Any]:
    """Return operational on-hand counts per product_code (WAREHOUSE_STOCK)."""
    con = _ro_connect(warehouse_db_path)
    on_hand: Dict[str, int] = {}
    states_by_code: Dict[str, Dict[str, int]] = {}
    blank_on_hand = 0
    if con is None:
        return {"on_hand": on_hand, "states_by_code": states_by_code, "blank_on_hand": 0}
    try:
        rows = con.execute(
            "SELECT product_code, state FROM inventory_state"
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        con.close()
    for r in rows:
        pc = (r["product_code"] or "").strip()
        st = r["state"] or ""
        if st in _ON_HAND_STATES:
            if pc:
                on_hand[pc] = on_hand.get(pc, 0) + 1
                states_by_code.setdefault(pc, {})
                states_by_code[pc][st] = states_by_code[pc].get(st, 0) + 1
            else:
                blank_on_hand += 1
    return {"on_hand": on_hand, "states_by_code": states_by_code,
            "blank_on_hand": blank_on_hand}


# ── classification helpers ──────────────────────────────────────────────────

def _qty_mismatch_severity(op: float, fis: float) -> str:
    if fis == 0 and op > 0:
        return SEV_CRITICAL            # stock in Dashboard, wFirma says zero
    if abs(op - fis) >= _QTY_MISMATCH_HIGH_ABS:
        return SEV_HIGH
    return SEV_MEDIUM


def _diff(dtype: str, severity: str, product_code: str,
          dashboard_qty, wfirma_qty, detail: str = "",
          warehouse_id: str = "", warehouse_name: str = "") -> Dict[str, Any]:
    return {
        "type": dtype,
        "severity": severity,
        "product_code": product_code,
        "dashboard_qty": dashboard_qty,
        "wfirma_qty": wfirma_qty,
        "difference": (None if dashboard_qty is None or wfirma_qty is None
                       else round(float(dashboard_qty) - float(wfirma_qty), 3)),
        "warehouse_id": warehouse_id,
        "warehouse_name": warehouse_name,
        "detail": detail,
        "recommended_action": _RECOMMENDED_ACTION.get(dtype, ""),
    }


def compute_fiscal_reconciliation(
    *,
    operational: Dict[str, Any],
    fiscal: Dict[str, Any],
    mirror_rows: List[Dict[str, Any]],
    warehouse_filter: str = "",
) -> Dict[str, Any]:
    """Pure comparison. All inputs already gathered; no I/O here."""
    op_on_hand: Dict[str, int] = dict(operational.get("on_hand") or {})
    states_by_code: Dict[str, Dict[str, int]] = operational.get("states_by_code") or {}
    blank_on_hand = int(operational.get("blank_on_hand") or 0)

    # Mirror mapping counts per product_code (canonical accessor rows).
    mirror_count: Dict[str, int] = {}
    for m in mirror_rows or []:
        pc = (m.get("product_code") or "").strip()
        if pc:
            mirror_count[pc] = mirror_count.get(pc, 0) + 1
    mirror_codes: Set[str] = set(mirror_count.keys())

    fiscal_available = bool(fiscal.get("available"))
    differences: List[Dict[str, Any]] = []

    # ── fiscal unavailable → honest degraded report, no invented differences ──
    if not fiscal_available:
        objects = len(op_on_hand)
        summary = _summary(
            total_compared=objects, matching=0, differences=[],
            missing_dashboard=0, missing_wfirma=0, unknown_mappings=0,
            operational_codes=objects, fiscal_codes=0,
            blank_on_hand=blank_on_hand,
        )
        return {
            "generated_at": _now_iso(),
            "fiscal_source": "unavailable",
            "fiscal_unavailable_reason": fiscal.get("unavailable_reason"),
            "warehouse_filter": warehouse_filter,
            "warehouses": [],
            "summary": summary,
            "differences": [],
        }

    # ── aggregate fiscal by product_code (sum across warehouses) ──────────────
    fis_by_code: Dict[str, float] = {}
    fis_warehouses_by_code: Dict[str, Set[str]] = {}
    fis_ids_by_code: Dict[str, Set[str]] = {}
    fiscal_entries = fiscal.get("entries") or []
    for e in fiscal_entries:
        pc = (e.get("product_code") or "").strip()
        if not pc:
            # good with no product code — cannot be mapped
            differences.append(_diff(
                T_UNKNOWN_PRODUCT, SEV_MEDIUM, "", None, e.get("count"),
                detail=f"wFirma good id={e.get('wfirma_id')} has no product code",
                warehouse_id=e.get("warehouse_id", ""),
                warehouse_name=e.get("warehouse_name", ""),
            ))
            continue
        fis_by_code[pc] = fis_by_code.get(pc, 0.0) + float(e.get("count") or 0.0)
        fis_warehouses_by_code.setdefault(pc, set()).add(e.get("warehouse_id", ""))
        fis_ids_by_code.setdefault(pc, set()).add(e.get("wfirma_id", ""))

    fiscal_codes: Set[str] = set(fis_by_code.keys())

    # ── unknown warehouses (requested id absent in wFirma) ────────────────────
    for wid in fiscal.get("unknown_warehouses") or []:
        differences.append(_diff(
            T_UNKNOWN_WAREHOUSE, SEV_HIGH, "", None, None,
            detail=f"warehouse id {wid} not found in wFirma",
            warehouse_id=wid,
        ))

    # ── duplicate wFirma good for one product_code ────────────────────────────
    for pc, ids in fis_ids_by_code.items():
        if len(ids) > 1:
            differences.append(_diff(
                T_DUPLICATE_PRODUCT, SEV_HIGH, pc,
                op_on_hand.get(pc), fis_by_code.get(pc),
                detail=f"{len(ids)} wFirma goods share product code {pc}",
            ))

    # ── duplicate mirror mapping ──────────────────────────────────────────────
    for pc, n in mirror_count.items():
        if n > 1:
            differences.append(_diff(
                T_DUPLICATE_MAPPING, SEV_CRITICAL, pc,
                op_on_hand.get(pc), fis_by_code.get(pc),
                detail=f"product code {pc} maps to {n} wFirma ids in the mirror",
            ))

    # ── warehouse split (informational) ───────────────────────────────────────
    for pc, whs in fis_warehouses_by_code.items():
        if len(whs) > 1:
            differences.append(_diff(
                T_WAREHOUSE_MISMATCH, SEV_LOW, pc,
                op_on_hand.get(pc), fis_by_code.get(pc),
                detail=f"fiscal stock split across {len(whs)} warehouses",
            ))

    # ── per-product comparison over the union of codes ────────────────────────
    matching = 0
    missing_wfirma = 0
    missing_dashboard = 0
    mapping_missing = 0
    all_codes = set(op_on_hand.keys()) | fiscal_codes
    for pc in sorted(all_codes):
        op = op_on_hand.get(pc, 0)
        fis = fis_by_code.get(pc)  # None if absent in fiscal
        in_fiscal = pc in fiscal_codes

        if op > 0 and pc not in mirror_codes:
            # Unmapped operational stock cannot be fiscally reconciled at all.
            differences.append(_diff(
                T_MAPPING_MISSING, SEV_HIGH, pc, op,
                (fis if in_fiscal else None),
                detail="no wFirma mirror mapping for this product code",
            ))
            mapping_missing += 1
            continue

        if op > 0 and not in_fiscal:
            differences.append(_diff(
                T_MISSING_WFIRMA, SEV_HIGH, pc, op, 0,
                detail="in Dashboard stock; absent from wFirma warehouse",
            ))
            missing_wfirma += 1
        elif op == 0 and in_fiscal and fis > 0:
            differences.append(_diff(
                T_MISSING_DASHBOARD, SEV_MEDIUM, pc, 0, fis,
                detail="in wFirma warehouse; no Dashboard on-hand pieces",
            ))
            missing_dashboard += 1
        elif in_fiscal and op != fis:
            differences.append(_diff(
                T_QTY_MISMATCH, _qty_mismatch_severity(op, fis), pc, op, fis,
                detail=f"Dashboard on-hand {op} vs wFirma {fiscal_num(fis)}",
            ))
        elif in_fiscal and op == fis:
            matching += 1

    # severity-first, then type, then code
    differences.sort(key=lambda d: (
        _SEV_ORDER.get(d["severity"], 9), d["type"], d["product_code"]))

    summary = _summary(
        total_compared=len(all_codes),
        matching=matching,
        differences=differences,
        missing_dashboard=missing_dashboard,
        missing_wfirma=missing_wfirma,
        unknown_mappings=mapping_missing,
        operational_codes=len(op_on_hand),
        fiscal_codes=len(fiscal_codes),
        blank_on_hand=blank_on_hand,
    )

    return {
        "generated_at": _now_iso(),
        "fiscal_source": "wfirma",
        "fiscal_unavailable_reason": None,
        "warehouse_filter": warehouse_filter,
        "warehouses": fiscal.get("warehouses") or [],
        "summary": summary,
        "differences": differences,
    }


def fiscal_num(v) -> Any:
    f = round(float(v), 3)
    return int(f) if f == int(f) else f


def _summary(*, total_compared, matching, differences, missing_dashboard,
             missing_wfirma, unknown_mappings, operational_codes, fiscal_codes,
             blank_on_hand) -> Dict[str, Any]:
    by_severity: Dict[str, int] = {SEV_CRITICAL: 0, SEV_HIGH: 0, SEV_MEDIUM: 0, SEV_LOW: 0}
    by_type: Dict[str, int] = {}
    for d in differences:
        by_severity[d["severity"]] = by_severity.get(d["severity"], 0) + 1
        by_type[d["type"]] = by_type.get(d["type"], 0) + 1
    return {
        "total_compared": total_compared,
        "matching": matching,
        "mismatched": len(differences),
        "missing_dashboard": missing_dashboard,
        "missing_wfirma": missing_wfirma,
        "unknown_mappings": unknown_mappings,
        "operational_product_codes": operational_codes,
        "fiscal_product_codes": fiscal_codes,
        "blank_product_code_on_hand": blank_on_hand,
        "by_severity": by_severity,
        "by_type": by_type,
    }


# ── filtering (server-side, applied to the differences list) ─────────────────

def _apply_filters(report: Dict[str, Any], *, warehouse: str = "",
                   product: str = "", severity: str = "",
                   difference_type: str = "", search: str = "") -> Dict[str, Any]:
    diffs = report.get("differences") or []
    w = (warehouse or "").strip()
    p = (product or "").strip().upper()
    sev = (severity or "").strip().upper()
    dt = (difference_type or "").strip()
    q = (search or "").strip().upper()

    def _keep(d: Dict[str, Any]) -> bool:
        if w and str(d.get("warehouse_id") or "") != w:
            return False
        if p and p not in (d.get("product_code") or "").upper():
            return False
        if sev and d.get("severity") != sev:
            return False
        if dt and d.get("type") != dt:
            return False
        if q:
            hay = " ".join(str(d.get(k) or "") for k in
                           ("product_code", "type", "detail",
                            "warehouse_name", "recommended_action")).upper()
            if q not in hay:
                return False
        return True

    filtered = [d for d in diffs if _keep(d)]
    out = dict(report)
    out["differences"] = filtered
    out["filtered_count"] = len(filtered)
    return out


# ── production entry point ───────────────────────────────────────────────────

def run_fiscal_reconciliation(
    *,
    warehouse_id: Optional[str] = None,
    record: bool = True,
    warehouse: str = "",
    product: str = "",
    severity: str = "",
    difference_type: str = "",
    search: str = "",
) -> Dict[str, Any]:
    """Resolve authorities, run the read-only reconciliation, record an audit run,
    and return the (optionally filtered) report."""
    from ..core.config import settings
    from . import warehouse_db

    t0 = perf_counter()
    reservation_path = Path(settings.storage_root) / "reservation_queue.db"

    operational = _read_operational(getattr(warehouse_db, "_db_path", None))
    fiscal = wfirma_fiscal_inventory.read_fiscal_inventory(warehouse_id)
    try:
        mirror_rows = reservation_db.list_mirror_products(reservation_path)
    except Exception:
        mirror_rows = []

    report = compute_fiscal_reconciliation(
        operational=operational,
        fiscal=fiscal,
        mirror_rows=mirror_rows,
        warehouse_filter=(warehouse_id or ""),
    )
    duration_ms = int((perf_counter() - t0) * 1000)
    report["duration_ms"] = duration_ms

    if record:
        summ = report.get("summary") or {}
        try:
            audit_path = Path(settings.storage_root) / "inventory_reconciliation.db"
            audit_db.record_run(audit_path, {
                "run_at": report.get("generated_at"),
                "warehouse_filter": warehouse_id or "",
                "fiscal_source": report.get("fiscal_source"),
                "duration_ms": duration_ms,
                "objects_checked": summ.get("total_compared", 0),
                "matching": summ.get("matching", 0),
                "mismatched": summ.get("mismatched", 0),
                "missing_dashboard": summ.get("missing_dashboard", 0),
                "missing_wfirma": summ.get("missing_wfirma", 0),
                "unknown_mappings": summ.get("unknown_mappings", 0),
                "differences_total": summ.get("mismatched", 0),
                "by_severity": summ.get("by_severity", {}),
                "by_type": summ.get("by_type", {}),
            })
        except Exception:
            # Audit persistence must never break the read-only report.
            pass

    if any([warehouse, product, severity, difference_type, search]):
        report = _apply_filters(
            report, warehouse=warehouse, product=product, severity=severity,
            difference_type=difference_type, search=search)
    return report


def get_status() -> Dict[str, Any]:
    """Canonical status shape for the reconciliation surface (last run)."""
    from ..core.config import settings
    audit_path = Path(settings.storage_root) / "inventory_reconciliation.db"
    last = audit_db.get_last_run(audit_path)
    return {
        "healthy": True,
        "running": False,
        "last_run": last,
        "fiscal_configured": wfirma_fiscal_inventory._api_configured(),
    }
