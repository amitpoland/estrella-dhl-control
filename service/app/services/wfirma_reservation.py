"""
wfirma_reservation.py — Reservation readiness + dry-run payload builder.

Commercial authority (operator-locked 2026-08-09):
  Draft Proforma.editable_lines_json is the commercial snapshot when present:
  one reservation line per Draft line (design_no → product_code → qty/unit_price/
  currency). Distinct Draft unit prices are NEVER aggregated away merely because
  they share a wFirma product_code / good_id.

Fallback (no Draft for the client, or per-SKU gap):
  sales_packing_lines + v_sales_to_wfirma. Resolver keys by design_no. An already-
  correct invoice-style product_code on the sales line is used as-is and must not
  become UNMATCHED.

Stock gate (unchanged authority):
  stock_ok = all packing scan_codes under the invoice product_code are
  current_status='dispatched'. Warehouse receipt confirmation is ADVISORY only.

Persistence:
  get_reservation_preview(..., persist=True) upserts local drafts/lines for Create.
  build_reservation_plan(..., persist=False) and dry_run_reservation() do not write.
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from ..core.config import settings
from ..core.logging import get_logger
from . import document_db as ddb
from . import packing_db as pdb
from . import warehouse_db as wdb
from . import warehouse_audit as waudit
from . import wfirma_capabilities as wfc
from . import wfirma_db as wfdb
from . import customer_identity_resolver as _cir
from . import wfirma_client as wfcli

log = get_logger(__name__)

_WS = re.compile(r"\s+")
# Invoice / wFirma product symbols look like EJL/26-27/492-1 (slash-separated).
_INVOICE_PC = re.compile(r".+/.+")


def _filter_stub_doc(sdoc: dict) -> bool:
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


def _looks_like_invoice_product_code(pc: str) -> bool:
    pc = (pc or "").strip()
    if not pc or pc.upper().startswith("UNMATCHED:"):
        return False
    return bool(_INVOICE_PC.match(pc))


def _product_matched(inv_pc: str) -> Tuple[bool, Optional[Dict[str, Any]]]:
    if not inv_pc or inv_pc.startswith("UNMATCHED:") or wfdb._db_path is None:
        return False, None
    prod = wfdb.get_product(inv_pc)
    ok = bool(
        prod
        and prod.get("wfirma_product_id")
        and prod.get("sync_status") == "matched"
    )
    return ok, prod


def _resolve_inv_pc(
    *,
    design_no: str,
    product_code: str,
    draft_map: Dict[str, str],
    sales_to_pc: Dict[Tuple[str, str], Optional[str]],
    doc_id: str,
    known_invoice_pcs: Optional[Set[str]] = None,
) -> str:
    """Resolve to invoice/wFirma product_code. Never invent mappings.

    Order:
      1. Explicit product_code already matched in wfirma_products (keep as-is —
         invoice-style codes like EJL/26-27/492-1 must never become UNMATCHED)
      2. Draft map by design_no (then by product_code key)
      3. v_sales_to_wfirma by design_no / product_code (sales SKU → packing invoice ref)
      4. product_code that already appears as a packing/invoice product_code symbol
      5. UNMATCHED:<sales SKU>

    Do NOT treat every slash-containing string as an invoice product_code —
    sales SKUs like WR/SKU-ALPHA also contain slashes and must go through the
    packing map (step 3), not short-circuit as canonical symbols.
    """
    pc_raw = (product_code or "").strip()
    dn_raw = (design_no or "").strip()
    dn_key = _norm(dn_raw)
    pc_key = _norm(pc_raw)

    if pc_raw and not pc_raw.upper().startswith("UNMATCHED:"):
        matched, _ = _product_matched(pc_raw)
        if matched:
            return pc_raw

    if dn_key and dn_key in draft_map:
        return draft_map[dn_key]

    if pc_key and pc_key in draft_map:
        return draft_map[pc_key]

    view_pc = (
        sales_to_pc.get((doc_id, dn_key))
        or sales_to_pc.get((doc_id, pc_key))
        or ""
    )
    if view_pc:
        return str(view_pc).strip()

    # Already the invoice/packing symbol (e.g. sales line carries EJL/… directly)
    # but not yet in wfirma_products — keep symbol so missing_product gate fires,
    # not a false UNMATCHED rewrite of a correct code.
    if (
        pc_raw
        and not pc_raw.upper().startswith("UNMATCHED:")
        and known_invoice_pcs
        and pc_raw in known_invoice_pcs
    ):
        return pc_raw

    # Sales SKU with no packing/draft link → UNMATCHED (prefer product_code key)
    sku_label = pc_raw or dn_raw or "UNKNOWN"
    return f"UNMATCHED:{_norm(sku_label)}"


def _load_draft_bundle(batch_id: str) -> Dict[str, Dict[str, Any]]:
    """client_norm → {draft, lines, map design_no→product_code (first wins for fallback)}.

    ``lines`` preserves every Draft commercial line (no price aggregation).
    """
    out: Dict[str, Dict[str, Any]] = {}
    try:
        from .proforma_invoice_link_db import list_drafts_for_batch as _list_drafts
        _pf_db = settings.storage_root / "proforma_links.db"
        for draft in _list_drafts(_pf_db, batch_id):
            cname = _norm(draft.client_name or "")
            if not cname:
                continue
            try:
                dlines = json.loads(draft.editable_lines_json or "[]") or []
            except Exception:
                dlines = []
            dmap: Dict[str, str] = {}
            for dl in dlines:
                dn = _norm(str(dl.get("design_no") or ""))
                pc = str(dl.get("product_code") or "").strip()
                if dn and pc and dn not in dmap:
                    dmap[dn] = pc
            out[cname] = {
                "draft": draft,
                "lines": dlines,
                "map": dmap,
                "currency": (draft.currency or "").strip().upper(),
                "proforma_draft_id": getattr(draft, "id", None),
            }
    except Exception as exc:
        log.debug("wfirma_reservation: draft load failed (non-fatal): %s", exc)
    return out


def _row_from_commercial(
    *,
    line_index: int,
    inv_pc: str,
    qty: float,
    unit_price: float,
    currency: str,
    design_no: str,
    create_product_allowed: bool,
    stock_status_fn,
) -> Dict[str, Any]:
    unmatched = inv_pc.startswith("UNMATCHED:")
    st = "missing" if unmatched else stock_status_fn(inv_pc)
    sok = st == "dispatched"
    product_match, prod = _product_matched(inv_pc)
    product_ok_for_ready = product_match or create_product_allowed
    row_ready = (
        sok
        and not unmatched
        and product_ok_for_ready
        and qty > 0
    )
    return {
        "line_index": line_index,
        "product_code": inv_pc,
        "quantity": qty,
        "unit_price": unit_price,
        "currency": currency,
        "stock_ok": sok,
        "stock_status": st,
        "product_match": product_match,
        "wfirma_product_id": (prod or {}).get("wfirma_product_id") or "",
        "product_name_pl": (prod or {}).get("product_name_pl") or "",
        "unit": (prod or {}).get("unit") or "szt.",
        "design_no": design_no or "",
        "design_nos": [design_no] if design_no else [],
        "ready": row_ready,
        "line_total": round(float(qty) * float(unit_price), 4),
    }


def build_reservation_plan(
    batch_id: str,
    *,
    client_name: Optional[str] = None,
    persist: bool = False,
) -> Dict[str, Any]:
    """Build reservation readiness / commercial plan for a batch.

    persist=False → pure local reads only (no wfirma_db draft upsert).
    persist=True  → also upsert reservation drafts/lines for Create.
    Optional client_name filters the documents list to one client.
    """
    empty = _empty_response(batch_id)
    if not _ready() or not batch_id:
        return empty

    caps = wfc.get_capabilities()
    wfirma_configured = caps["api_configured"]
    reservation_supported = caps["reservation_supported"]
    create_product_allowed = caps["create_product_allowed"]
    create_customer_allowed = caps["create_customer_allowed"]

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

    sales_docs = ddb.get_sales_documents(batch_id)
    if not sales_docs:
        return empty

    all_spl = ddb.get_sales_packing_lines(batch_id)
    spl_by_doc: Dict[str, List[Dict]] = defaultdict(list)
    for spl in all_spl:
        spl_by_doc[spl["sales_document_id"]].append(spl)

    draft_bundle = _load_draft_bundle(batch_id)

    sales_to_pc: Dict[Tuple[str, str], Optional[str]] = {}
    for v in ddb.query_sales_to_wfirma(batch_id):
        sales_to_pc[(
            v["sales_document_id"],
            _norm(v["sales_design_no"] or ""),
        )] = v["wfirma_product_code"]

    packing_rows = pdb.get_packing_lines_for_batch(batch_id)
    inv_pc_scan_codes: Dict[str, List[str]] = defaultdict(list)
    known_invoice_pcs: Set[str] = set()
    for pl in packing_rows:
        inv_pc = pl.get("product_code") or ""
        if inv_pc:
            known_invoice_pcs.add(inv_pc)
        sc = pl.get("scan_code") or wdb.scan_code_for_packing_line(pl)
        if inv_pc and sc and sc not in inv_pc_scan_codes[inv_pc]:
            inv_pc_scan_codes[inv_pc].append(sc)

    # Invoice price/currency — used ONLY on the sales-fallback path when a sales
    # packing line carries no commercial price/currency of its own. Draft path
    # never reads these (Draft editable lines are the commercial snapshot).
    inv_lines = ddb.get_invoice_lines_for_batch(batch_id)
    inv_price: Dict[str, float] = {}
    inv_currency: Dict[str, str] = {}
    for il in inv_lines:
        pc = il.get("product_code") or ""
        if pc and pc not in inv_price:
            price = il.get("rate_usd") or il.get("unit_price") or 0
            inv_price[pc] = float(price)
            inv_currency[pc] = (il.get("currency") or "PLN").upper()
        if pc:
            known_invoice_pcs.add(pc)

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

    missing_scans = waudit.get_missing_scans(batch_id)
    invalid_flows = waudit.get_invalid_flows(batch_id)
    orphans = waudit.get_orphan_inventory(batch_id)

    batch_advisories: List[str] = []
    if missing_scans:
        batch_advisories.append(
            f"{len(missing_scans)} packing line(s) awaiting warehouse confirmation "
            f"(advisory — optional traceability, does not block reservation)"
        )
    if invalid_flows:
        batch_advisories.append(f"{len(invalid_flows)} invalid scan flow(s) detected (advisory)")
    if orphans:
        batch_advisories.append(f"{len(orphans)} orphan warehouse record(s) (advisory)")
    audit_clean = not bool(batch_advisories)

    blocking_reasons: List[str] = []
    if not wfirma_configured:
        blocking_reasons.append(
            "wFirma API not configured (WFIRMA_API_LOGIN / PASSWORD / COMPANY_ID)"
        )
    if wfirma_configured and not reservation_supported:
        blocking_reasons.append(
            "wFirma warehouse module not enabled "
            "(WFIRMA_WAREHOUSE_MODULE_ENABLED / WFIRMA_WAREHOUSE_ID)"
        )

    client_filter = (client_name or "").strip()
    documents: List[Dict[str, Any]] = []

    for sdoc in sales_docs:
        doc_id = sdoc.get("id") or sdoc.get("document_id") or ""
        client = sdoc.get("client_name") or ""
        client_ref = sdoc.get("client_ref") or ""
        doc_no = sdoc.get("sales_doc_no") or client_ref
        client_cid = str(sdoc.get("client_contractor_id") or "").strip()

        if _filter_stub_doc(sdoc):
            continue
        if client_filter and client.strip() != client_filter:
            continue

        customer_ok = bool(client and client.strip())
        cust_rec = wfdb.get_customer(client) if wfdb._db_path is not None else None
        customer_match = bool(
            cust_rec
            and cust_rec.get("wfirma_customer_id")
            and cust_rec.get("match_status") == "matched"
        )
        if not customer_match and client_cid:
            try:
                if _cir.resolve_by_contractor_id(client_cid) is not None:
                    customer_match = True
            except Exception:
                pass

        bundle = draft_bundle.get(_norm(client))
        draft_map = (bundle or {}).get("map") or {}
        doc_currency = (bundle or {}).get("currency") or ""
        commercial_source = "draft_proforma" if bundle and bundle.get("lines") else "sales_fallback"

        rows: List[Dict[str, Any]] = []

        if commercial_source == "draft_proforma":
            for i, dl in enumerate(bundle["lines"]):
                dn = str(dl.get("design_no") or "").strip()
                pc_hint = str(dl.get("product_code") or "").strip()
                qty = float(dl.get("qty") if dl.get("qty") is not None else (dl.get("quantity") or 0))
                unit_price = float(
                    dl.get("unit_price") if dl.get("unit_price") is not None else (dl.get("price") or 0)
                )
                line_ccy = str(dl.get("currency") or doc_currency or "PLN").strip().upper()
                if not doc_currency:
                    doc_currency = line_ccy
                inv_pc = _resolve_inv_pc(
                    design_no=dn,
                    product_code=pc_hint,
                    draft_map=draft_map,
                    sales_to_pc=sales_to_pc,
                    doc_id=doc_id,
                    known_invoice_pcs=known_invoice_pcs,
                )
                # Draft product_code is canonical when present and non-empty.
                if pc_hint and not pc_hint.upper().startswith("UNMATCHED:"):
                    inv_pc = pc_hint
                rows.append(_row_from_commercial(
                    line_index=i,
                    inv_pc=inv_pc,
                    qty=qty,
                    unit_price=unit_price,
                    currency=line_ccy or doc_currency or "PLN",
                    design_no=dn,
                    create_product_allowed=create_product_allowed,
                    stock_status_fn=_stock_status,
                ))
        else:
            # Sales fallback — preserve distinct unit prices (never merge different
            # prices for the same product_code). Identical (pc, price, currency)
            # lines may sum quantity. Price/currency fall back to invoice_lines
            # only when the sales row itself carries none.
            provisional: List[Dict[str, Any]] = []
            for i, spl_row in enumerate(spl_by_doc.get(doc_id, [])):
                dn = str(spl_row.get("design_no") or "").strip()
                pc_hint = str(spl_row.get("product_code") or "").strip()
                qty = float(spl_row.get("quantity") or 0)
                unit_price = float(spl_row.get("unit_price") or 0)
                line_ccy = str(spl_row.get("currency") or "").strip().upper()
                inv_pc = _resolve_inv_pc(
                    design_no=dn,
                    product_code=pc_hint,
                    draft_map=draft_map,
                    sales_to_pc=sales_to_pc,
                    doc_id=doc_id,
                    known_invoice_pcs=known_invoice_pcs,
                )
                if not inv_pc.startswith("UNMATCHED:"):
                    if unit_price <= 0 and inv_pc in inv_price:
                        unit_price = inv_price[inv_pc]
                    if not line_ccy and inv_pc in inv_currency:
                        line_ccy = inv_currency[inv_pc]
                if not line_ccy:
                    line_ccy = doc_currency or "PLN"
                if not doc_currency:
                    doc_currency = line_ccy
                provisional.append({
                    "line_index": i,
                    "inv_pc": inv_pc,
                    "qty": qty,
                    "unit_price": unit_price,
                    "currency": line_ccy,
                    "design_no": dn or pc_hint,
                })

            # Merge only identical commercial keys (same pc + unit_price + currency).
            merged: Dict[Tuple[str, float, str], Dict[str, Any]] = {}
            order: List[Tuple[str, float, str]] = []
            for p in provisional:
                key = (p["inv_pc"], float(p["unit_price"]), p["currency"])
                if key not in merged:
                    merged[key] = {
                        "line_index": len(order),
                        "inv_pc": p["inv_pc"],
                        "qty": 0.0,
                        "unit_price": p["unit_price"],
                        "currency": p["currency"],
                        "design_nos": [],
                    }
                    order.append(key)
                merged[key]["qty"] += float(p["qty"])
                dn = p["design_no"]
                if dn and dn not in merged[key]["design_nos"]:
                    merged[key]["design_nos"].append(dn)

            for key in order:
                m = merged[key]
                row = _row_from_commercial(
                    line_index=m["line_index"],
                    inv_pc=m["inv_pc"],
                    qty=m["qty"],
                    unit_price=m["unit_price"],
                    currency=m["currency"],
                    design_no=(m["design_nos"][0] if m["design_nos"] else ""),
                    create_product_allowed=create_product_allowed,
                    stock_status_fn=_stock_status,
                )
                row["design_nos"] = list(m["design_nos"])
                rows.append(row)

        if not doc_currency:
            doc_currency = "PLN"

        total_value = sum(float(r["line_total"]) for r in rows)

        doc_blocking: List[str] = []
        doc_advisories: List[str] = []
        if not customer_ok:
            doc_blocking.append("client_name is empty")
        if not customer_match and not create_customer_allowed:
            doc_blocking.append(
                f"customer {client!r} not matched in wfirma_customers "
                f"(register via PUT /api/v1/wfirma/customers/<name>)"
            )

        unmatched_rows = [r for r in rows if r["product_code"].startswith("UNMATCHED:")]
        missing_product = [
            r for r in rows
            if not r["product_match"] and not r["product_code"].startswith("UNMATCHED:")
        ]
        # Unresolved required products BLOCK Create (honest gate — not advisory).
        if unmatched_rows:
            codes = [r["product_code"] for r in unmatched_rows]
            doc_blocking.append(
                f"{len(unmatched_rows)} line(s) unresolved to a wFirma product: "
                + ", ".join(codes[:5]) + ("…" if len(codes) > 5 else "")
            )
        if missing_product and not create_product_allowed:
            codes = [r["product_code"] for r in missing_product]
            doc_blocking.append(
                f"{len(missing_product)} product(s) not in wfirma_products: "
                + ", ".join(codes[:3]) + ("…" if len(codes) > 3 else "")
            )
        no_stock = [
            r for r in rows
            if not r["stock_ok"] and not r["product_code"].startswith("UNMATCHED:")
        ]
        if no_stock:
            doc_blocking.append(
                f"{len(no_stock)} line(s) not yet dispatched from warehouse"
            )

        # customer_ok is required for row.ready path via doc_ready; rows themselves
        # do not encode customer_match so a customer miss still blocks the doc.
        doc_ready = (
            bool(rows)
            and not doc_blocking
            and customer_ok
            and (customer_match or create_customer_allowed)
            and all(r["ready"] for r in rows)
        )

        if persist and wfdb._db_path is not None:
            try:
                draft_id = wfdb.upsert_reservation_draft(
                    batch_id,
                    client,
                    client_ref=client_ref,
                    currency=doc_currency,
                    warehouse_id=settings.wfirma_warehouse_id,
                    ready_to_create=doc_ready,
                    client_contractor_id=client_cid,
                )
                wfdb.replace_reservation_lines(draft_id, [
                    {
                        "line_index": r["line_index"],
                        "product_code": r["product_code"],
                        "qty": r["quantity"],
                        "unit_price": r["unit_price"],
                        "currency": r["currency"],
                        "stock_ok": r["stock_ok"],
                        "product_ok": r["product_match"],
                        "product_name_pl": r.get("product_name_pl") or "",
                        "design_no": r.get("design_no") or "",
                    }
                    for r in rows
                    if not r["product_code"].startswith("UNMATCHED:")
                ])
            except Exception as exc:
                log.warning("wfirma_db draft persist failed: %s", exc)

        created_for_client = next(
            (d for d in _created_drafts
             if (d.get("client_name") or "").strip() == client.strip()),
            None,
        )

        documents.append({
            "sales_doc_no": doc_no,
            "client_name": client,
            "client_ref": client_ref,
            "client_contractor_id": client_cid,
            "contractor_resolved": bool(client_cid),
            "customer_ok": customer_ok,
            "customer_match": customer_match,
            "wfirma_customer_id": (
                (cust_rec or {}).get("wfirma_customer_id")
                or (client_cid if customer_match else "")
                or ""
            ),
            "ready": doc_ready,
            "total_value": round(total_value, 2),
            "currency": doc_currency,
            "commercial_source": commercial_source,
            "proforma_draft_id": (bundle or {}).get("proforma_draft_id"),
            "blocking_reasons": doc_blocking,
            "advisories": doc_advisories,
            "rows": rows,
            "reservation_exists": bool(created_for_client),
            "wfirma_reservation_id": (
                (created_for_client or {}).get("wfirma_reservation_id") or ""
            ),
        })

    all_docs_ready = bool(documents) and all(d["ready"] for d in documents)
    ready_to_create = (
        all_docs_ready
        and wfirma_configured
        and reservation_supported
    )
    batch_blocking_reasons = list(blocking_reasons)
    if not all_docs_ready:
        for d in documents:
            if not d["ready"] and d["blocking_reasons"]:
                blocking_reasons.append(
                    f"{d['client_name']!r}: " + "; ".join(d["blocking_reasons"])
                )

    # Plan-level currency: dominant commercial currency across documents/rows.
    ccy_counts: Dict[str, int] = defaultdict(int)
    for d in documents:
        for r in d.get("rows") or []:
            c = (r.get("currency") or d.get("currency") or "").upper()
            if c:
                ccy_counts[c] += 1
        if not d.get("rows") and d.get("currency"):
            ccy_counts[str(d["currency"]).upper()] += 1
    plan_currency = (
        max(ccy_counts.items(), key=lambda kv: kv[1])[0] if ccy_counts else "PLN"
    )

    return {
        "batch_id": batch_id,
        "audit_clean": audit_clean,
        "wfirma_configured": wfirma_configured,
        "reservation_supported": reservation_supported,
        "ready_to_create": ready_to_create,
        "blocking_reasons": blocking_reasons,
        "batch_blocking_reasons": batch_blocking_reasons,
        "batch_advisories": batch_advisories,
        "currency": plan_currency,
        "reservation_exists": reservation_exists,
        "reservation_id": reservation_id,
        "documents": documents,
        "persisted": bool(persist),
    }


def get_reservation_preview(batch_id: str) -> Dict[str, Any]:
    """Preview + persist local drafts/lines (Create prep). No wFirma HTTP."""
    return build_reservation_plan(batch_id, persist=True)


def dry_run_reservation(batch_id: str, client_name: str) -> Dict[str, Any]:
    """Pure dry-run: readiness + exact wFirma XML payload. Zero HTTP. Zero persist."""
    plan = build_reservation_plan(
        batch_id, client_name=client_name, persist=False,
    )
    docs = plan.get("documents") or []
    doc = next(
        (d for d in docs if (d.get("client_name") or "").strip() == (client_name or "").strip()),
        None,
    )
    if doc is None:
        return {
            "ok": False,
            "code": "CLIENT_NOT_FOUND",
            "error": f"No reservation document for client_name={client_name!r}",
            "batch_id": batch_id,
            "client_name": client_name,
            "plan": plan,
            "payload": None,
            "xml": None,
        }

    unresolved = [
        r for r in (doc.get("rows") or [])
        if r.get("product_code", "").startswith("UNMATCHED:") or not r.get("product_match")
    ]
    lines_out = []
    for r in doc.get("rows") or []:
        if r.get("product_code", "").startswith("UNMATCHED:"):
            continue
        lines_out.append({
            "line_index": r.get("line_index"),
            "design_no": r.get("design_no") or "",
            "product_code": r.get("product_code"),
            "wfirma_product_id": r.get("wfirma_product_id") or "",
            "qty": r.get("quantity"),
            "unit_price": r.get("unit_price"),
            "currency": r.get("currency") or doc.get("currency"),
            "line_total": r.get("line_total"),
            "unit": r.get("unit") or "szt.",
            "product_name": r.get("product_name_pl") or r.get("product_code"),
            "stock_ok": r.get("stock_ok"),
            "stock_status": r.get("stock_status"),
        })

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    contractor_id = str(doc.get("wfirma_customer_id") or "").strip()
    # Build the commercial XML whenever customer + product IDs resolve, even if
    # stock/readiness still blocks live Create — operator must review the exact
    # payload before approving the live write.
    commercial_complete = bool(
        contractor_id
        and lines_out
        and not unresolved
        and all(ln.get("wfirma_product_id") for ln in lines_out)
    )
    xml = None
    if commercial_complete:
        req = wfcli.ReservationRequest(
            batch_id=batch_id,
            client_name=client_name,
            wfirma_contractor_id=contractor_id,
            wfirma_warehouse_id=settings.wfirma_warehouse_id or "",
            date=today,
            currency=doc.get("currency") or "PLN",
            description=f"Batch {batch_id} · {client_name}"[:200],
            lines=[
                wfcli.ReservationLine(
                    product_code=ln["product_code"],
                    wfirma_good_id=ln["wfirma_product_id"],
                    product_name=ln["product_name"],
                    qty=float(ln["qty"] or 0),
                    unit_price=float(ln["unit_price"] or 0),
                    unit=ln.get("unit") or "szt.",
                    currency=ln.get("currency") or doc.get("currency") or "PLN",
                )
                for ln in lines_out
            ],
        )
        xml = wfcli._build_reservation_xml(req)

    payload = {
        "batch_id": batch_id,
        "client_name": client_name,
        "contractor_id": contractor_id,
        "document_currency": doc.get("currency"),
        "commercial_source": doc.get("commercial_source"),
        "proforma_draft_id": doc.get("proforma_draft_id"),
        "warehouse_id": settings.wfirma_warehouse_id or "",
        "date": today,
        "lines": lines_out,
        "line_count": len(lines_out),
        "total_value": doc.get("total_value"),
        "unresolved_count": len(unresolved),
        "unresolved": [
            {
                "line_index": r.get("line_index"),
                "design_no": r.get("design_no"),
                "product_code": r.get("product_code"),
            }
            for r in unresolved
        ],
        "ready_for_live_create": bool(doc.get("ready")),
        "commercial_complete": commercial_complete,
        "blocking_reasons": list(doc.get("blocking_reasons") or []) + list(
            plan.get("batch_blocking_reasons") or []
        ),
        "batch_advisories": plan.get("batch_advisories") or [],
    }

    return {
        "ok": True,
        "code": "DRY_RUN",
        "error": "",
        "batch_id": batch_id,
        "client_name": client_name,
        "would_call_wfirma": False,
        "payload": payload,
        "xml": xml,
        "plan_document": doc,
    }


def _empty_response(batch_id: str) -> Dict[str, Any]:
    caps = wfc.get_capabilities()
    return {
        "batch_id": batch_id,
        "audit_clean": False,
        "wfirma_configured": caps["api_configured"],
        "reservation_supported": caps["reservation_supported"],
        "ready_to_create": False,
        "blocking_reasons": ["no sales documents found"],
        "batch_blocking_reasons": ["no sales documents found"],
        "batch_advisories": [],
        "currency": "PLN",
        "reservation_exists": False,
        "reservation_id": None,
        "documents": [],
        "persisted": False,
    }
