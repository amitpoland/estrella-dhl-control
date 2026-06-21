"""
wfirma_reservation.py — Read-only reservation preview builder.

Produces a structured preview of what would be sent to wFirma as reservations,
one per sales document (client), grouped at the invoice product_code level.

Key schema rules (do NOT change these):
  sales.product_code  = SKU / design code   (e.g. "CSTR07596")
  packing.design_no   = SKU / design code   (matches sales.product_code)
  packing.product_code = invoice line ref   (e.g. "EJL/26-27/015-6")  ← wFirma product

wFirma product symbol MUST = packing.product_code (invoice line ref), NOT design_no.
Design rows are internal trace only — never sent to wFirma.

Grouping:
  sales_packing_line.product_code (SKU)
    → packing_line.design_no  (same SKU)
    → packing_line.product_code (invoice ref)
    → invoice_line.rate_usd + currency

One preview document per sales_document (client_name + client_ref).
One reservation row per distinct invoice product_code within that document.

Stock gate:
  stock_ok = all design scan_codes under this invoice product_code have
             current_status = 'dispatched' in warehouse

Customer / product gate:
  customer_match = client_name found in wfirma_customers with wfirma_customer_id set
  product_match  = product_code found in wfirma_products with wfirma_product_id set

ready_to_create (full gate):
  audit clean AND stock dispatched AND customer name present AND customer matched
  AND all products matched (or create_product_allowed) AND wFirma configured
  AND reservation_supported (warehouse module enabled)
"""
from __future__ import annotations

import re
import sqlite3
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

from ..core.config import settings
from ..core.logging import get_logger
from . import document_db as ddb
from . import packing_db as pdb
from . import warehouse_db as wdb
from . import warehouse_audit as waudit
from . import wfirma_capabilities as wfc
from . import wfirma_db as wfdb

log = get_logger(__name__)

_WS = re.compile(r"\s+")


def _filter_stub_doc(sdoc: dict) -> bool:
    """Sprint-24 §4.1: return True if this sales_doc is a stub that should be filtered.

    A stub has an empty client_name AND no sales_doc_no. These are auto-generated
    placeholder rows produced during sync, not real drafts. Real unassigned drafts
    have a doc_number even if client_name is empty; those are kept (return False).
    """
    client = (sdoc.get("client_name") or "").strip()
    doc_no = (sdoc.get("sales_doc_no") or sdoc.get("client_ref") or "").strip()
    return not client and not doc_no


def _norm(s: str) -> str:
    return _WS.sub(" ", (s or "").strip()).upper()


def _ready() -> bool:
    return (
        ddb._db_path is not None
        and pdb._db_path is not None
        and wdb._db_path is not None
    )


def _wcon() -> sqlite3.Connection:
    con = sqlite3.connect(str(wdb._db_path), check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


# ── Main preview ──────────────────────────────────────────────────────────────

def get_reservation_preview(batch_id: str) -> Dict[str, Any]:
    """
    Return a wFirma reservation preview for all sales documents in *batch_id*.

    Also persists drafts and lines to wfirma_db so they can be reviewed
    before POST /reservations/create is called.

    Returns
    -------
    {
        "batch_id":             str,
        "audit_clean":          bool,
        "wfirma_configured":    bool,
        "reservation_supported": bool,
        "ready_to_create":      bool,   # full gate — ALL conditions must be met
        "blocking_reasons":     list[str],
        "currency":             str,    # dominant currency from invoice_lines
        "reservation_exists":   bool,   # True if any draft for this batch has status='created'
        "reservation_id":       str | None,  # wfirma_reservation_id from first 'created' draft
        "documents": [
            {
                "sales_doc_no":   str,
                "client_name":    str,
                "client_ref":     str,
                "customer_ok":    bool,   # client_name is non-empty
                "customer_match": bool,   # found in wfirma_customers with wfirma_customer_id
                "ready":          bool,
                "total_value":    float,
                "blocking_reasons": list[str],
                "rows": [
                    {
                        "product_code":  str,       # invoice ref = wFirma product symbol
                        "quantity":      float,
                        "unit_price":    float,
                        "currency":      str,
                        "stock_ok":      bool,      # all scan_codes dispatched
                        "stock_status":  str,       # dispatched | received | missing
                        "product_match": bool,      # found in wfirma_products
                        "design_nos":    list[str], # traceability only
                        "ready":         bool,
                    }
                ]
            }
        ]
    }
    """
    empty = _empty_response(batch_id)
    if not _ready() or not batch_id:
        return empty

    # ── 0. wFirma capability check ────────────────────────────────────────────
    caps = wfc.get_capabilities()
    wfirma_configured    = caps["api_configured"]
    reservation_supported = caps["reservation_supported"]
    create_product_allowed  = caps["create_product_allowed"]
    create_customer_allowed = caps["create_customer_allowed"]

    # ── 0b. Existing reservation lookup (read-only — never writes) ────────────
    # Check wfirma_reservation_drafts for any draft that has already been
    # successfully submitted (status='created').  This is set by Phase 3 create
    # flow only; the preview never mutates status or wfirma_reservation_id.
    _existing_drafts: List[Dict[str, Any]] = (
        wfdb.list_reservation_drafts(batch_id) if wfdb._db_path is not None else []
    )
    _created_drafts = [
        d for d in _existing_drafts
        if d.get("status") == "created" and d.get("wfirma_reservation_id", "")
    ]
    reservation_exists = bool(_created_drafts)
    reservation_id: Optional[str] = (
        _created_drafts[0]["wfirma_reservation_id"] if _created_drafts else None
    )

    # ── 1. Sales documents ────────────────────────────────────────────────────
    sales_docs = ddb.get_sales_documents(batch_id)
    if not sales_docs:
        return empty

    # ── 2. Sales packing lines, keyed by sales_document_id ───────────────────
    all_spl = ddb.get_sales_packing_lines(batch_id)
    spl_by_doc: Dict[str, List[Dict]] = defaultdict(list)
    for spl in all_spl:
        spl_by_doc[spl["sales_document_id"]].append(spl)

    # ── 3. Sales → wFirma product_code resolution ────────────────────────────
    # Pulled from the read-only v_sales_to_wfirma view (document_db).
    # Keyed by (sales_document_id, normalized sales_design_no).
    # Replaces the previous in-memory dn_to_inv_pc rebuild.
    sales_to_pc: Dict[Tuple[str, str], Optional[str]] = {}
    for v in ddb.query_sales_to_wfirma(batch_id):
        sales_to_pc[(
            v["sales_document_id"],
            _norm(v["sales_design_no"] or ""),
        )] = v["wfirma_product_code"]

    # inv_pc → scan_codes index is still needed for warehouse stock checks.
    packing_rows = pdb.get_packing_lines_for_batch(batch_id)
    inv_pc_scan_codes: Dict[str, List[str]] = defaultdict(list)
    for pl in packing_rows:
        inv_pc = pl.get("product_code") or ""
        sc     = pl.get("scan_code") or wdb.scan_code_for_packing_line(pl)
        if inv_pc and sc and sc not in inv_pc_scan_codes[inv_pc]:
            inv_pc_scan_codes[inv_pc].append(sc)

    # ── 4. Invoice lines: price + currency per invoice product_code ───────────
    inv_lines = ddb.get_invoice_lines_for_batch(batch_id)
    inv_price: Dict[str, float] = {}
    inv_currency: Dict[str, str] = {}
    for il in inv_lines:
        pc = il.get("product_code") or ""
        if pc and pc not in inv_price:
            price = il.get("rate_usd") or il.get("unit_price") or 0
            inv_price[pc]    = float(price)
            inv_currency[pc] = (il.get("currency") or "PLN").upper()

    currency_counts = Counter(inv_currency.values())
    batch_currency  = currency_counts.most_common(1)[0][0] if currency_counts else "PLN"

    # ── 5. Warehouse stock ────────────────────────────────────────────────────
    with _wcon() as con:
        wh_rows = con.execute(
            "SELECT scan_code, current_status FROM inventory_current_location WHERE batch_id=?",
            (batch_id,),
        ).fetchall()
    dispatched_codes: Set[str] = {
        r["scan_code"] for r in wh_rows if r["current_status"] == "dispatched"
    }
    received_codes: Set[str] = {r["scan_code"] for r in wh_rows}

    def _stock_status(inv_pc: str) -> str:
        scs = inv_pc_scan_codes.get(inv_pc, [])
        if not scs:
            return "missing"
        if all(sc in dispatched_codes for sc in scs):
            return "dispatched"
        if all(sc in received_codes for sc in scs):
            return "received"
        return "missing"

    def _stock_ok(inv_pc: str) -> bool:
        return _stock_status(inv_pc) == "dispatched"

    # ── 6. Audit gate ─────────────────────────────────────────────────────────
    missing_scans = waudit.get_missing_scans(batch_id)
    invalid_flows = waudit.get_invalid_flows(batch_id)
    orphans       = waudit.get_orphan_inventory(batch_id)

    blocking_reasons: List[str] = []
    if missing_scans:
        blocking_reasons.append(f"{len(missing_scans)} packing line(s) not yet scanned into warehouse")
    if invalid_flows:
        blocking_reasons.append(f"{len(invalid_flows)} invalid scan flow(s) detected")
    if orphans:
        blocking_reasons.append(f"{len(orphans)} orphan warehouse record(s)")

    audit_clean = not bool(blocking_reasons)

    # wFirma configuration blocking reasons
    if not wfirma_configured:
        blocking_reasons.append("wFirma API not configured (WFIRMA_API_LOGIN / PASSWORD / COMPANY_ID)")
    if wfirma_configured and not reservation_supported:
        blocking_reasons.append(
            "wFirma warehouse module not enabled "
            "(WFIRMA_WAREHOUSE_MODULE_ENABLED / WFIRMA_WAREHOUSE_ID)"
        )

    # ── 7. Build per-document preview ─────────────────────────────────────────
    # Sprint-24 §4.1: filter stub rows — empty client_name with no doc_number
    # are auto-generated placeholders, not real drafts. Real unassigned drafts
    # would have a doc_number; those are rendered with their doc_number as label.
    documents: List[Dict[str, Any]] = []

    for sdoc in sales_docs:
        doc_id     = sdoc.get("id") or sdoc.get("document_id") or ""
        client     = sdoc.get("client_name") or ""
        client_ref = sdoc.get("client_ref") or ""
        doc_no     = sdoc.get("sales_doc_no") or client_ref
        # PR-2: authoritative contractor reference carried into reservation
        # readiness (reference only — does not change ready_to_create gating).
        client_cid = str(sdoc.get("client_contractor_id") or "").strip()

        # Filter: skip stub rows — empty client_name with no doc_number.
        # Uses the named helper so the filter logic is unit-testable.
        if _filter_stub_doc(sdoc):
            continue

        customer_ok = bool(client and client.strip())

        # Customer mapping lookup
        cust_rec      = wfdb.get_customer(client) if wfdb._db_path is not None else None
        customer_match = bool(
            cust_rec
            and cust_rec.get("wfirma_customer_id")
            and cust_rec.get("match_status") == "matched"
        )

        # Aggregate sales rows → invoice product_code groups
        group_qty: Dict[str, float]     = defaultdict(float)
        group_dns: Dict[str, List[str]] = defaultdict(list)

        doc_spl = spl_by_doc.get(doc_id, [])
        for spl_row in doc_spl:
            sku    = _norm(spl_row.get("product_code") or "")
            inv_pc = sales_to_pc.get((doc_id, sku)) or ""
            qty    = float(spl_row.get("quantity") or 0)
            dn_raw = spl_row.get("design_no") or spl_row.get("product_code") or ""

            if not inv_pc:
                inv_pc = f"UNMATCHED:{sku}"

            group_qty[inv_pc] += qty
            if dn_raw and dn_raw not in group_dns[inv_pc]:
                group_dns[inv_pc].append(dn_raw)

        # Build rows
        rows: List[Dict[str, Any]] = []
        for inv_pc, qty in sorted(group_qty.items()):
            unmatched   = inv_pc.startswith("UNMATCHED:")
            st          = "missing" if unmatched else _stock_status(inv_pc)
            sok         = st == "dispatched"
            unit_price  = 0.0 if unmatched else inv_price.get(inv_pc, 0.0)
            currency    = batch_currency if unmatched else inv_currency.get(inv_pc, batch_currency)

            # Product mapping lookup
            prod_rec      = wfdb.get_product(inv_pc) if wfdb._db_path is not None else None
            product_match = bool(
                not unmatched
                and prod_rec
                and prod_rec.get("wfirma_product_id")
                and prod_rec.get("sync_status") == "matched"
            )

            # Row is ready when:
            #   stock dispatched + customer name + not unmatched
            #   + product known (or creation is allowed)
            product_ok_for_ready = product_match or create_product_allowed
            row_ready = (
                sok
                and customer_ok
                and not unmatched
                and product_ok_for_ready
            )

            rows.append({
                "product_code":  inv_pc,
                "quantity":      qty,
                "unit_price":    unit_price,
                "currency":      currency,
                "stock_ok":      sok,
                "stock_status":  st,
                "product_match": product_match,
                "design_nos":    group_dns.get(inv_pc, []),
                "ready":         row_ready,
            })

        total_value = sum(r["unit_price"] * r["quantity"] for r in rows)

        doc_blocking: List[str] = []
        if not customer_ok:
            doc_blocking.append("client_name is empty")
        if not customer_match and not create_customer_allowed:
            doc_blocking.append(
                f"customer {client!r} not matched in wfirma_customers "
                f"(register via PUT /api/v1/wfirma/customers/<name>)"
            )
        unmatched_rows  = [r for r in rows if r["product_code"].startswith("UNMATCHED:")]
        missing_product = [r for r in rows if not r["product_match"] and not r["product_code"].startswith("UNMATCHED:")]
        if unmatched_rows:
            doc_blocking.append(
                f"{len(unmatched_rows)} SKU(s) not linked to packing lines"
            )
        if missing_product and not create_product_allowed:
            codes = [r["product_code"] for r in missing_product]
            doc_blocking.append(
                f"{len(missing_product)} product(s) not in wfirma_products: "
                + ", ".join(codes[:3]) + ("…" if len(codes) > 3 else "")
            )
        no_stock = [r for r in rows if not r["stock_ok"] and not r["product_code"].startswith("UNMATCHED:")]
        if no_stock:
            doc_blocking.append(
                f"{len(no_stock)} product(s) not yet dispatched from warehouse"
            )

        doc_ready = (
            bool(rows)
            and not doc_blocking
            and customer_ok
            and (customer_match or create_customer_allowed)
            and all(r["ready"] for r in rows)
        )

        # Persist draft + lines to wfirma_db for later creation
        if wfdb._db_path is not None:
            try:
                draft_id = wfdb.upsert_reservation_draft(
                    batch_id,
                    client,
                    client_ref=client_ref,
                    currency=batch_currency,
                    warehouse_id=settings.wfirma_warehouse_id,
                    ready_to_create=doc_ready,
                    client_contractor_id=client_cid,
                )
                for row in rows:
                    wfdb.upsert_reservation_line(
                        draft_id,
                        row["product_code"],
                        qty=row["quantity"],
                        unit_price=row["unit_price"],
                        currency=row["currency"],
                        stock_ok=row["stock_ok"],
                        product_ok=row["product_match"],
                    )
            except Exception as exc:
                log.warning("wfirma_db draft persist failed: %s", exc)

        documents.append({
            "sales_doc_no":    doc_no,
            "client_name":     client,
            "client_ref":      client_ref,
            # PR-2: contractor reference chain — the authoritative Customer
            # Master identity bound at intake, carried through to reservation
            # readiness. Reference only; readiness gating is unchanged.
            "client_contractor_id": client_cid,
            "contractor_resolved":  bool(client_cid),
            "customer_ok":     customer_ok,
            "customer_match":  customer_match,
            "ready":           doc_ready,
            "total_value":     round(total_value, 2),
            "blocking_reasons": doc_blocking,
            "rows":            rows,
        })

    # ── 8. Overall readiness ──────────────────────────────────────────────────
    all_docs_ready  = bool(documents) and all(d["ready"] for d in documents)
    ready_to_create = (
        audit_clean
        and all_docs_ready
        and wfirma_configured
        and reservation_supported
    )

    # Batch-level (warehouse + wFirma config) blockers — these block EVERY client
    # in the batch and are NOT specific to any one draft (e.g. "84 packing line(s)
    # not yet scanned" counts the whole batch's packing, not one draft's billed
    # lines). Captured BEFORE the per-document roll-ups are folded into
    # blocking_reasons below, so the frontend can render batch-scope vs
    # draft-scope distinctly. Display-only — does NOT affect ready_to_create.
    batch_blocking_reasons = list(blocking_reasons)

    if not all_docs_ready and audit_clean:
        for d in documents:
            if not d["ready"] and d["blocking_reasons"]:
                blocking_reasons.append(
                    f"{d['client_name']!r}: " + "; ".join(d["blocking_reasons"])
                )

    return {
        "batch_id":             batch_id,
        "audit_clean":          audit_clean,
        "wfirma_configured":    wfirma_configured,
        "reservation_supported": reservation_supported,
        "ready_to_create":      ready_to_create,
        "blocking_reasons":     blocking_reasons,
        "batch_blocking_reasons": batch_blocking_reasons,
        "currency":             batch_currency,
        "reservation_exists":   reservation_exists,
        "reservation_id":       reservation_id,
        "documents":            documents,
    }


def _empty_response(batch_id: str) -> Dict[str, Any]:
    caps = wfc.get_capabilities()
    return {
        "batch_id":             batch_id,
        "audit_clean":          False,
        "wfirma_configured":    caps["api_configured"],
        "reservation_supported": caps["reservation_supported"],
        "ready_to_create":      False,
        "blocking_reasons":     ["no sales documents found"],
        "batch_blocking_reasons": ["no sales documents found"],
        "currency":             "PLN",
        "reservation_exists":   False,
        "reservation_id":       None,
        "documents":            [],
    }
