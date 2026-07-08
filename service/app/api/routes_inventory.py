"""
Inventory read-only routes.

Currently exposes:
  GET /api/v1/inventory/stage2/aggregate — 5-bucket Stage 2 summary.

NO POST/PUT/PATCH/DELETE. Future write paths must be added in
separate router files with explicit SECURITY review.
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..core.security import require_api_key
from ..services.inventory_batch_state import get_batch_state
from ..services.inventory_piece_view import get_piece_detail
from ..services.inventory_reconciliation_service import run_reconciliation
from ..services import inventory_fiscal_reconciliation_service as fiscal_recon
from ..services.inventory_stage2_aggregator import aggregate_stage2


router = APIRouter(
    prefix="/api/v1/inventory",
    tags=["inventory"],
    dependencies=[Depends(require_api_key)],
)


def _validate_as_of(as_of: Optional[str]) -> Optional[str]:
    if as_of is None:
        return None
    try:
        # Accept ISO 8601; handle the "Z" UTC suffix that
        # datetime.fromisoformat() supports only on Python 3.11+.
        normalized = as_of.replace("Z", "+00:00") if as_of.endswith("Z") else as_of
        datetime.fromisoformat(normalized)
        return as_of  # echo verbatim
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid as_of timestamp: {as_of!r} — expected ISO 8601",
        )


@router.get("/reconciliation")
def get_inventory_reconciliation() -> dict:
    """Read-only Inventory Intelligence reconciliation report (Phase 1).

    Reconciles the inventory authority (inventory_state) against the purchase
    authority (packing_lines quantity) and the identity authority (product_master,
    ADVISORY only — never a blocker). Returns per-batch metrics + an advisory
    health status. GET only; performs NO mutation and offers NO repair suggestions.
    """
    return run_reconciliation()


# ── WF-2: Fiscal reconciliation (Dashboard operational vs wFirma fiscal) ──────
# Read-only. Compares operational piece-stock (inventory_state) against wFirma
# fiscal quantity (goods/find by warehouse_id). Never writes either system; the
# only write is WF-2's own audit-run record. No auto-correction.

@router.get("/fiscal-reconciliation")
def get_fiscal_reconciliation(
    warehouse_id: Optional[str] = Query(None, description="wFirma warehouse id to read (default: configured/all)"),
    warehouse: Optional[str] = Query(None, description="filter results by warehouse id"),
    product: Optional[str] = Query(None, description="filter results by product code (substring)"),
    severity: Optional[str] = Query(None, description="filter by LOW|MEDIUM|HIGH|CRITICAL"),
    difference_type: Optional[str] = Query(None, description="filter by difference type"),
    search: Optional[str] = Query(None, description="free-text filter"),
) -> dict:
    """Read-only fiscal reconciliation report (a VIEW — not recorded as a run).

    Compares Dashboard operational on-hand stock against wFirma fiscal quantity
    and returns a classified, severity-ranked difference report. Performs NO
    mutation and offers NO automatic correction. When wFirma is unavailable the
    report is honestly marked ``fiscal_source="unavailable"``.
    """
    return fiscal_recon.run_fiscal_reconciliation(
        warehouse_id=warehouse_id, record=False,
        warehouse=warehouse or "", product=product or "",
        severity=severity or "", difference_type=difference_type or "",
        search=search or "",
    )


@router.post("/fiscal-reconciliation/run")
def run_fiscal_reconciliation_now(
    warehouse_id: Optional[str] = Query(None, description="wFirma warehouse id to read (default: configured/all)"),
) -> dict:
    """Run Now — executes the read-only reconciliation and records an audit run.

    Records only run METADATA (timestamp, warehouse, duration, counts) to WF-2's
    own audit DB. Writes nothing to inventory_state, wFirma, or any Master.
    """
    return fiscal_recon.run_fiscal_reconciliation(warehouse_id=warehouse_id, record=True)


@router.get("/fiscal-reconciliation/status")
def get_fiscal_reconciliation_status() -> dict:
    """Canonical status for the reconciliation surface (last recorded run)."""
    return fiscal_recon.get_status()


@router.get("/stage2/aggregate")
def get_stage2_aggregate(
    as_of: Optional[str] = Query(
        None,
        description="Optional ISO 8601 timestamp. Echoed verbatim. "
                    "If omitted, server uses current UTC time.",
    ),
) -> dict:
    """Read-only Stage 2 aggregation. GET only."""
    validated = _validate_as_of(as_of)
    return aggregate_stage2(as_of=validated)


@router.get("/pieces/{piece_id}")
def get_inventory_piece_detail(
    piece_id: str,
    as_of: Optional[str] = Query(
        None,
        description="Optional ISO 8601 timestamp. Echoed verbatim. "
                    "If omitted, server uses current UTC time.",
    ),
) -> dict:
    """Read-only per-piece inventory detail. Returns state row + history.

    Honest empty: unknown piece_id yields found=False (HTTP 200, not 404).
    """
    validated = _validate_as_of(as_of)
    return get_piece_detail(piece_id, as_of=validated)


@router.get("/state/{batch_id}")
def get_inventory_state_for_batch(
    batch_id: str,
    as_of: Optional[str] = Query(
        None,
        description="Optional ISO 8601 timestamp. Echoed verbatim. "
                    "If omitted, server uses current UTC time.",
    ),
) -> dict:
    """Read-only per-batch inventory state. Returns counts + per-piece list.

    Honest empty: an unknown batch_id yields zero counts and an empty
    pieces list (HTTP 200, not 404). Callers distinguish via `total`.
    """
    validated = _validate_as_of(as_of)
    return get_batch_state(batch_id, as_of=validated)


# ── BE-2: Stock Promotion Notes (PROJECT_STATE DECISIONS "BE-2 Stock
# Promotion Note", 2026-07-02). Read-only — the Notes are WRITTEN solely by
# run_stock_promotion() via stock_promotion_note_db. GET only, per this
# file's contract.

@router.get("/promotion-notes/{batch_id}")
def list_promotion_notes(batch_id: str) -> dict:
    """Note headers for a batch, newest first.

    Honest empty: unknown batch_id yields an empty list (HTTP 200).
    """
    from ..services.stock_promotion_note_db import list_notes
    notes = list_notes(batch_id)
    return {"batch_id": batch_id, "total": len(notes), "notes": notes}


@router.get("/promotion-note/{note_no:path}")
def get_promotion_note(note_no: str) -> dict:
    """One Note, header + lines. note_no contains slashes (SPN/NNN/YYYY) —
    the :path converter follows the routes_warehouse location_code:path
    precedent. Unknown note_no → 404 NOTE_NOT_FOUND.
    """
    from ..services.stock_promotion_note_db import get_note
    note = get_note(note_no)
    if note is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOTE_NOT_FOUND",
                    "detail": f"promotion note {note_no!r} not found"},
        )
    return note


# ── C-3e: merchandising-grade batch read (Phase-C Wave 2 — backend only) ─────

@router.get("/merchandising/{batch_id}")
def get_merchandising_view(batch_id: str) -> dict:
    """Packing-list-grade merchandising rows for a batch, joined with the
    live inventory state per piece (inventory_state ⋈ packing_lines).

    Backs the wireframe DELIVERABLE-2 Stock Hub columns (PK SR · CTG ·
    Client PO · Design No · Karat · Color · Quality · Dia Wt · Qty) — the
    data already lives in packing_lines (W2-A6); client_po is a best-effort
    sales-side display enrichment (advisory, '' when absent). Read-only;
    UI wiring is Wave 3 / U-3.

    Honest empty: unknown batch_id yields rows=[] (HTTP 200).
    """
    from ..services import packing_db as pdb
    from ..services import inventory_state_engine as ise

    packing = pdb.get_packing_lines_for_batch(batch_id) or []

    # {scan_code: state} — one query via the engine's batch map.
    state_by_scan: dict = {}
    try:
        for state, scans in (ise.list_all_states_for_batch(batch_id) or {}).items():
            for sc in scans:
                state_by_scan[sc] = state
    except Exception:
        state_by_scan = {}

    # Best-effort client_po enrichment from the sales side (advisory only —
    # never gates; design_no/product_code keyed).
    client_po_by_key: dict = {}
    try:
        from ..services import document_db as ddb
        for sl in ddb.get_sales_packing_lines(batch_id) or []:
            po = (sl.get("client_po") or "").strip()
            if not po:
                continue
            for key in ((sl.get("product_code") or "").strip(),
                        (sl.get("design_no") or "").strip()):
                if key and key not in client_po_by_key:
                    client_po_by_key[key] = po
    except Exception:
        client_po_by_key = {}

    rows = []
    for line in packing:
        sc = line.get("scan_code") or ""
        try:
            sc = sc or pdb._compute_scan_code(line) or ""
        except Exception:
            sc = sc or ""
        pc = (line.get("product_code") or "").strip()
        dn = (line.get("design_no") or "").strip()
        rows.append({
            "scan_code":      sc,
            "product_code":   pc,
            "design_no":      dn,
            "batch_no":       line.get("batch_no") or "",
            "pack_sr":        line.get("pack_sr"),
            "ctg":            line.get("item_type") or "",
            "client_po":      client_po_by_key.get(dn) or client_po_by_key.get(pc) or "",
            "karat":          line.get("karat") or "",
            "color":          line.get("metal_color") or "",
            "quality":        line.get("quality_string") or "",
            "dia_wt":         line.get("diamond_weight"),
            "size":           line.get("size") or "",
            "qty":            line.get("quantity"),
            "uom":            line.get("uom") or "",
            "gross_weight":   line.get("gross_weight"),
            "net_weight":     line.get("net_weight"),
            "state":          state_by_scan.get(sc, ""),
        })
    return {"ok": True, "batch_id": batch_id, "count": len(rows), "rows": rows}


# ── C-3f: movement / document-trail read (Phase-C Wave 2 — backend only) ─────

@router.get("/movements/{batch_id}")
def list_batch_movements(batch_id: str, limit: int = 1000) -> dict:
    """Lifecycle movement trail for every piece of a batch, newest first —
    the engine's append-only inventory_state_events. Document trails hang
    off the referenced endpoints (promotion notes, sample/returns registers,
    per-piece unified timeline at /pieces/{piece_id}). Read-only; UI wiring
    is Wave 3.

    Honest empty: unknown batch_id yields events=[] (HTTP 200).
    """
    from ..services import inventory_state_engine as ise
    from ..services.stock_promotion_note_db import list_notes

    events = ise.list_events_for_batch(batch_id, limit=limit)
    try:
        note_count = len(list_notes(batch_id) or [])
    except Exception:
        note_count = 0
    return {
        "ok":       True,
        "batch_id": batch_id,
        "count":    len(events),
        "events":   events,
        "document_trails": {
            "promotion_notes": note_count,
            "promotion_notes_endpoint": f"/api/v1/inventory/promotion-notes/{batch_id}",
            "samples_endpoint":  "/api/v1/inventory/samples",
            "returns_endpoint":  "/api/v1/inventory/returns",
        },
    }
