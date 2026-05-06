"""
routes_proforma.py — wFirma proforma preview + create-shell endpoints.

  POST /api/v1/proforma/preview/{batch_id}/{client_name}
        Read-only resolution: design_no → wfirma product_code, currency, FX,
        per-line stock_status, readiness gates. No writes, no live wFirma
        calls.

  POST /api/v1/proforma/create/{batch_id}/{client_name}
        Create-shell. Runs the same preview, enforces readiness gates,
        persists a local pending_local draft (idempotent on
        (batch_id, client_name)). Does NOT yet call wFirma — the live
        create wiring is deferred.
"""
from __future__ import annotations

import json
import sqlite3
import xml.etree.ElementTree as ET
from collections import Counter
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from ..core.config import settings
from ..core.security import require_api_key
from ..core.logging import get_logger
from ..services import document_db as ddb
from ..services import packing_db  as pdb
from ..services import warehouse_db as wdb  # noqa: F401  (kept for cross-DB queries)
from ..services import wfirma_db   as wfdb
from ..services import inventory_state_engine as ise
from ..services import proforma_invoice_link_db as pildb
from ..services import wfirma_client

log    = get_logger(__name__)
router = APIRouter(prefix="/api/v1/proforma", tags=["proforma"])
_auth  = Depends(require_api_key)


def _norm(s: str) -> str:
    return (s or "").strip().upper()


# ── Stock helpers (read-only, no writes) ─────────────────────────────────────
# Proforma readiness uses the lifecycle state model, not the physical
# DISPATCH scan: a proforma can be issued for goods that are present in
# WAREHOUSE_STOCK but have not yet shipped.

def _scan_codes_per_product(batch_id: str) -> Dict[str, List[str]]:
    """{ wfirma_product_code: [scan_code, ...] } from packing_lines."""
    if pdb._db_path is None:
        return {}
    out: Dict[str, List[str]] = {}
    with sqlite3.connect(str(pdb._db_path), check_same_thread=False) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT product_code, scan_code FROM packing_lines "
            "WHERE batch_id=? AND scan_code IS NOT NULL",
            (batch_id,),
        ).fetchall()
    for r in rows:
        pc = r["product_code"] or ""
        sc = r["scan_code"]    or ""
        if pc and sc:
            out.setdefault(pc, []).append(sc)
    return out


def _state_codes(batch_id: str) -> Dict[str, List[str]]:
    """{ inventory_state: [scan_code, ...] } for this batch."""
    out: Dict[str, List[str]] = {}
    for s in ise.STATES:
        try:
            for row in ise.list_by_state(s, batch_id=batch_id):
                out.setdefault(s, []).append(row["scan_code"])
        except Exception:
            # Engine unavailable — leave empty; downstream stock_ok=False.
            pass
    return out


# ── Warehouse readiness gate ─────────────────────────────────────────────────

def _check_warehouse_readiness(batch_id: str) -> List[str]:
    """
    Batch-level warehouse gate for proforma creation.

    Returns [] when audit.json is absent (graceful pass-through for test
    environments that don't seed a processed batch).

    Checks (in order):
      1. wfirma_export.wfirma_pz_doc_id is present in audit.json
      2. All product_codes in pz_rows.json are resolved in wfirma_products
         (wfirma_product_id set + sync_status == "matched")
      3. No price conflicts — same product_code must not carry two different
         unit_netto_pln values in pz_rows.json
    """
    output_dir = settings.storage_root / "outputs" / batch_id
    audit_path = output_dir / "audit.json"

    if not audit_path.exists():
        return []

    try:
        with audit_path.open() as f:
            audit = json.load(f)
    except Exception:
        return ["warehouse readiness check failed: could not read audit.json"]

    reasons: List[str] = []

    # 1. wfirma_pz_doc_id must exist
    wfirma_export = audit.get("wfirma_export") or {}
    pz_doc_id = (wfirma_export.get("wfirma_pz_doc_id") or "").strip()
    if not pz_doc_id:
        reasons.append(
            "warehouse PZ not yet created — run wFirma PZ create before issuing a proforma"
        )

    # 2+3. Inspect pz_rows.json for unresolved codes and price conflicts
    pz_rows_path = output_dir / "pz_rows.json"
    if not pz_rows_path.exists():
        return reasons

    try:
        with pz_rows_path.open() as f:
            pz_rows: List[Dict[str, Any]] = json.load(f)
    except Exception:
        reasons.append("warehouse readiness check failed: could not read pz_rows.json")
        return reasons

    # 2. Unresolved product_codes
    if wfdb._db_path is not None:
        all_codes = sorted({
            (r.get("product_code") or "").strip()
            for r in pz_rows
            if (r.get("product_code") or "").strip()
        })
        unresolved = []
        for code in all_codes:
            prod = wfdb.get_product(code)
            if not (prod and prod.get("wfirma_product_id") and prod.get("sync_status") == "matched"):
                unresolved.append(code)
        if unresolved:
            sample = ", ".join(unresolved[:3]) + ("…" if len(unresolved) > 3 else "")
            reasons.append(
                f"{len(unresolved)} product_code(s) unresolved in wfirma_products: {sample}"
            )

    # 3. Price conflicts
    prices_by_code: Dict[str, set] = {}
    for r in pz_rows:
        code = (r.get("product_code") or "").strip()
        price = r.get("unit_netto_pln")
        if code and price is not None:
            prices_by_code.setdefault(code, set()).add(round(float(price), 4))
    conflicts = sorted(code for code, prices in prices_by_code.items() if len(prices) > 1)
    if conflicts:
        sample = ", ".join(conflicts[:3]) + ("…" if len(conflicts) > 3 else "")
        reasons.append(
            f"{len(conflicts)} product_code(s) have price conflicts in pz_rows: {sample}"
        )

    return reasons


# ── Preview core (callable from both /preview and /create) ──────────────────

def _validate_args(batch_id: str, client_name: str) -> str:
    """Common path-arg validation. Returns the trimmed client_name."""
    if "/" in batch_id or ".." in batch_id:
        raise HTTPException(status_code=400, detail="Invalid batch_id.")
    cn = (client_name or "").strip()
    if not cn:
        raise HTTPException(status_code=400, detail="client_name is required.")
    return cn


def _build_preview(batch_id: str, client_name: str) -> Dict[str, Any]:
    """
    Pure read-only resolution. Returns the canonical preview dict.
    Identical body shape to what /preview emits over HTTP — used directly
    by the /create endpoint to share the exact same gating logic.
    """
    blocking_reasons: List[str] = []

    # ── 0. Warehouse readiness gate ───────────────────────────────────────────
    blocking_reasons.extend(_check_warehouse_readiness(batch_id))

    # ── 1. Resolution rows (sales → wFirma product_code) ────────────────────
    resolution_rows = [
        r for r in ddb.query_sales_to_wfirma(batch_id)
        if (r.get("client_name") or "").strip() == client_name
    ]
    if not resolution_rows:
        return {
            "ok":               False,
            "batch_id":         batch_id,
            "client_name":      client_name,
            "currency":         "unknown",
            "exchange_rate":    None,
            "ready":            False,
            "blocking_reasons": [f"no sales rows for client {client_name!r}"],
            "lines":            [],
        }

    # ── 2. Invoice pricing index: product_code → (unit_price, currency, fx) ─
    inv_lines = ddb.get_invoice_lines_for_batch(batch_id)
    inv_price:    Dict[str, float] = {}
    inv_currency: Dict[str, str]   = {}
    inv_fx:       Dict[str, Optional[float]] = {}
    for il in inv_lines:
        pc = il.get("product_code") or ""
        if not pc or pc in inv_price:
            continue
        price    = il.get("rate_usd") or il.get("unit_price") or 0
        currency = (il.get("currency") or "").upper() or "unknown"
        fx       = il.get("exchange_rate")
        inv_price[pc]    = float(price or 0)
        inv_currency[pc] = currency
        try:
            inv_fx[pc] = float(fx) if fx not in (None, "") else None
        except (TypeError, ValueError):
            inv_fx[pc] = None

    # ── 3. Stock readiness via inventory_state (NOT warehouse DISPATCH) ─────
    # A proforma may be issued when items are in WAREHOUSE_STOCK.
    # PURCHASE_TRANSIT (not yet received), SALES_TRANSIT (already promised
    # on another proforma/invoice), and CLOSED (delivered) all block
    # availability for a NEW proforma.
    sc_per_product   = _scan_codes_per_product(batch_id)
    state_codes      = _state_codes(batch_id)
    in_warehouse     = set(state_codes.get(ise.WAREHOUSE_STOCK,  []))
    in_purchase      = set(state_codes.get(ise.PURCHASE_TRANSIT, []))
    in_sales_transit = set(state_codes.get(ise.SALES_TRANSIT,    []))
    in_closed        = set(state_codes.get(ise.CLOSED,           []))

    def _stock_status(pc: str) -> str:
        scs = sc_per_product.get(pc, [])
        if not scs:
            return "no_scan_codes"
        if all(sc in in_warehouse for sc in scs):
            return "warehouse_stock"
        if any(sc in in_purchase for sc in scs):
            return "purchase_transit"
        if any(sc in in_sales_transit for sc in scs):
            return "sales_transit"
        if any(sc in in_closed for sc in scs):
            return "closed"
        return "missing_state"

    def _stock_ok(pc: str) -> bool:
        return _stock_status(pc) == "warehouse_stock"

    # ── 4. Build per-line response ──────────────────────────────────────────
    lines: List[Dict[str, Any]] = []
    unmatched_count    = 0
    missing_price      = 0
    missing_product    = 0
    stock_blocked: Counter = Counter()  # stock_status (excluding warehouse_stock)
    line_currencies: List[str] = []
    line_fx:            List[float] = []

    for r in resolution_rows:
        product_code = r.get("wfirma_product_code")  # may be None
        design_no    = r.get("sales_design_no") or ""
        qty          = float(r.get("qty") or 0)

        if not product_code:
            unmatched_count += 1
            lines.append({
                "product_code":  None,
                "design_no":     design_no,
                "qty":           qty,
                "unit_price":    None,
                "currency":      "unknown",
                "exchange_rate": None,
                "line_value":    None,
                "stock_ok":      False,
                "product_match": False,
            })
            continue

        unit_price = inv_price.get(product_code)
        currency   = inv_currency.get(product_code, "unknown")
        fx         = inv_fx.get(product_code)
        line_value = (unit_price * qty) if unit_price is not None else None

        if unit_price is None or currency == "unknown":
            missing_price += 1
        else:
            line_currencies.append(currency)
            if fx is not None:
                line_fx.append(fx)

        prod_rec = wfdb.get_product(product_code) if wfdb._db_path is not None else None
        product_match = bool(
            prod_rec
            and prod_rec.get("wfirma_product_id")
            and prod_rec.get("sync_status") == "matched"
        )
        if not product_match:
            missing_product += 1

        st = _stock_status(product_code)
        s_ok = (st == "warehouse_stock")
        if not s_ok:
            stock_blocked[st] += 1

        lines.append({
            "product_code":  product_code,
            "design_no":     design_no,
            "qty":           qty,
            "unit_price":    unit_price,
            "currency":      currency,
            "exchange_rate": fx,
            "line_value":    line_value,
            "stock_ok":      s_ok,
            "stock_status":  st,
            "product_match": product_match,
        })

    # ── 5. Header currency + FX (dominant across priced lines) ─────────────
    if line_currencies:
        currency = Counter(line_currencies).most_common(1)[0][0]
    else:
        currency = "unknown"
    exchange_rate = (sum(line_fx) / len(line_fx)) if line_fx else None

    # ── 6. Readiness gates ─────────────────────────────────────────────────
    if unmatched_count:
        blocking_reasons.append(
            f"{unmatched_count} sales design(s) not mapped to a wFirma product_code"
        )
    if missing_price:
        blocking_reasons.append(
            f"{missing_price} line(s) missing unit_price or currency in invoice_lines"
        )
    if missing_product:
        blocking_reasons.append(
            f"{missing_product} product(s) not matched in wfirma_products"
        )
    # Stock is reported per state; never written.
    _STATE_BLURB = {
        "purchase_transit": "still in PURCHASE_TRANSIT (not yet received in warehouse)",
        "sales_transit":    "already in SALES_TRANSIT (committed to another proforma/invoice)",
        "closed":           "in CLOSED state (already delivered)",
        "missing_state":    "have no inventory_state record (not seeded)",
        "no_scan_codes":    "have no scan_codes in packing_lines",
    }
    for state, count in stock_blocked.items():
        blurb = _STATE_BLURB.get(state, f"in unexpected state {state!r}")
        blocking_reasons.append(f"{count} product(s) {blurb}")

    # Customer match — local lookup only
    cust = wfdb.get_customer(client_name) if wfdb._db_path is not None else None
    customer_match = bool(
        cust
        and cust.get("wfirma_customer_id")
        and cust.get("match_status") == "matched"
    )
    if not customer_match:
        blocking_reasons.append(
            f"customer {client_name!r} not matched in wfirma_customers"
        )

    ready = not blocking_reasons

    return {
        "ok":               True,
        "batch_id":         batch_id,
        "client_name":      client_name,
        "currency":         currency,
        "exchange_rate":    exchange_rate,
        "ready":            ready,
        "blocking_reasons": blocking_reasons,
        "lines":            lines,
    }


# ── HTTP endpoints ──────────────────────────────────────────────────────────

@router.post("/preview/{batch_id}/{client_name:path}", dependencies=[_auth])
def proforma_preview(batch_id: str, client_name: str) -> JSONResponse:
    """Read-only proforma preview — same shape as _build_preview."""
    cn = _validate_args(batch_id, client_name)
    return JSONResponse(_build_preview(batch_id, cn))


# ── Local DB path for proforma drafts/links ─────────────────────────────────

def _proforma_db_path():
    return settings.storage_root / "proforma_links.db"


def _build_proforma_request(preview: Dict[str, Any]) -> "wfirma_client.ProformaRequest":
    """
    Build a wfirma_client.ProformaRequest from a ready preview dict.
    Caller-supplied values are NOT used here — every field is derived from
    server state (preview, packing_lines, wfirma_products / wfirma_customers).

    Resolves wFirma master IDs from the local mapping tables:
      - wfirma_customer_id from wfirma_customers (by client_name)
      - wfirma_product_id  from wfirma_products  (per product_code)
    Raises ValueError naming the missing mapping(s) if any required ID is
    absent. Caller must surface this as a blocked status — never as a 500.
    """
    client_name = (preview.get("client_name") or "").strip()
    cust = wfdb.get_customer(client_name) if wfdb._db_path is not None else None
    contractor_id = (cust or {}).get("wfirma_customer_id") or ""
    if not contractor_id:
        raise ValueError(
            f"wfirma_customers has no wfirma_customer_id for {client_name!r} — "
            "register the customer mapping before creating a proforma"
        )

    # ── Decide VAT context per customer (domestic / WDT / export) ──────────
    customer_country = ((cust or {}).get("country") or "").strip()
    customer_vat_id  = ((cust or {}).get("vat_id")  or "").strip()
    if not customer_country or (customer_country.upper() != "PL"
                                 and not customer_vat_id):
        # Local row is missing data — try a one-off live lookup against
        # wFirma's master to fill the decision (no DB write here; the
        # mapping refresh is a separate operator action).
        try:
            live = wfirma_client.search_customer(client_name)
        except Exception:
            live = None
        if live is not None:
            customer_country = customer_country or (live.country or "").strip()
            customer_vat_id  = customer_vat_id  or (live.nip     or "").strip()

    decision = wfirma_client.decide_proforma_vat_context(
        customer_country = customer_country,
        customer_vat_id  = customer_vat_id,
    )
    if decision["context"] == "blocked":
        raise ValueError(
            f"vat decision blocked for {client_name!r} "
            f"(country={customer_country!r}, vat_id={customer_vat_id!r}): "
            f"{decision['reason']}"
        )
    try:
        vat_code_id = wfirma_client.resolve_vat_code_id_for_context(
            decision["vat_code"]
        )
    except Exception as exc:
        raise ValueError(
            f"vat_code resolution failed for {decision['vat_code']!r} "
            f"({decision['reason']}): {exc}"
        )

    lines = []
    missing_products: List[str] = []
    for ln in preview.get("lines", []):
        pc = ln.get("product_code") or ""
        prod = wfdb.get_product(pc) if (pc and wfdb._db_path is not None) else None
        good_id = (prod or {}).get("wfirma_product_id") or ""
        if not good_id:
            missing_products.append(pc or "<unknown>")
            continue
        lines.append(wfirma_client.ReservationLine(
            product_code   = pc,
            wfirma_good_id = good_id,
            product_name   = ln.get("design_no") or pc,
            qty            = float(ln.get("qty") or 0),
            unit_price     = float(ln.get("unit_price") or 0),
            unit           = "szt.",
            currency       = (ln.get("currency") or preview.get("currency") or "PLN"),
        ))
    if missing_products:
        raise ValueError(
            "wfirma_products missing wfirma_product_id for: "
            + ", ".join(missing_products[:5])
            + ("…" if len(missing_products) > 5 else "")
        )

    return wfirma_client.ProformaRequest(
        client_name          = client_name,
        client_zip           = "",
        client_city          = "",
        lines                = lines,
        currency             = preview.get("currency") or "PLN",
        wfirma_contractor_id = contractor_id,
        vat_code_id          = vat_code_id,
    )


@router.post("/create/{batch_id}/{client_name:path}", dependencies=[_auth])
def proforma_create(batch_id: str, client_name: str) -> JSONResponse:
    """
    Create a wFirma proforma when all gates are satisfied.

    Status values:
      blocked        — preview not ready, OR settings gate is off
                       (no draft persisted, no live call)
      skipped        — existing draft is in pending_local or issued
      issued         — live wFirma call succeeded; draft.status='issued',
                       wfirma_proforma_id populated
      failed         — live wFirma call returned an error; draft.status='failed',
                       retryable

    Idempotent on (batch_id, client_name). Failed drafts ARE retryable;
    pending_local and issued drafts short-circuit as skipped.
    """
    cn = _validate_args(batch_id, client_name)
    preview = _build_preview(batch_id, cn)

    # ── 1. Existing draft short-circuit (issued / pending_local) ────────────
    existing = pildb.get_draft(_proforma_db_path(), batch_id, cn)
    if existing is not None and existing.status in ("issued", "pending_local"):
        return JSONResponse({
            "ok":                  True,
            "status":              "skipped",
            "existing_status":     existing.status,
            "batch_id":            batch_id,
            "client_name":         cn,
            "wfirma_proforma_id":  existing.wfirma_proforma_id,
            "currency":            existing.currency,
            "exchange_rate":       existing.exchange_rate,
            "draft_id":            existing.id,
        })

    # ── 2. Preview must be ready (independent of settings gate) ─────────────
    if not preview.get("ready"):
        return JSONResponse({
            "ok":               False,
            "status":            "blocked",
            "batch_id":          batch_id,
            "client_name":       cn,
            "blocking_reasons":  preview.get("blocking_reasons", []),
            "currency":          preview.get("currency"),
            "exchange_rate":     preview.get("exchange_rate"),
        })

    # ── 3. Settings gate — no live call when disabled ──────────────────────
    if not settings.wfirma_create_proforma_allowed:
        return JSONResponse({
            "ok":               False,
            "status":            "blocked",
            "batch_id":          batch_id,
            "client_name":       cn,
            "blocking_reasons":  ["wfirma proforma create disabled "
                                  "(WFIRMA_CREATE_PROFORMA_ALLOWED=false)"],
            "currency":          preview.get("currency"),
            "exchange_rate":     preview.get("exchange_rate"),
        })

    # ── 4. Lock or upsert the draft row (pending_local) ────────────────────
    source_lines = [
        {
            "product_code": ln.get("product_code"),
            "design_no":    ln.get("design_no"),
            "qty":          ln.get("qty"),
            "unit_price":   ln.get("unit_price"),
            "currency":     ln.get("currency"),
        }
        for ln in preview.get("lines", [])
    ]
    source_lines_json = json.dumps(source_lines, ensure_ascii=False)

    if existing is not None and existing.status == "failed":
        # Retry path — keep the same row, just record fresh source_lines.
        draft = existing
    else:
        draft, _ = pildb.upsert_pending_draft(
            _proforma_db_path(),
            batch_id          = batch_id,
            client_name       = cn,
            currency          = preview.get("currency", ""),
            exchange_rate     = preview.get("exchange_rate"),
            source_lines_json = source_lines_json,
        )

    # ── 5. Live wFirma call (only path with external write) ────────────────
    # _build_proforma_request resolves wfirma_customer_id + per-line
    # wfirma_product_id from local mappings. Missing mappings = blocked,
    # not failed — this is a configuration gate, not an external write
    # failure. Refusing to build avoids any chance of submitting a payload
    # that wFirma would reject or, worse, accept by creating a duplicate
    # contractor inline.
    try:
        req = _build_proforma_request(preview)
    except ValueError as exc:
        return JSONResponse({
            "ok":               False,
            "status":           "blocked",
            "batch_id":         batch_id,
            "client_name":      cn,
            "draft_id":         draft.id,
            "blocking_reasons": [str(exc)],
        })

    try:
        result = wfirma_client.create_proforma_draft(req)
    except Exception as exc:
        # Treat any unexpected failure (NotImplementedError, network, parse)
        # as a retryable failure. Mark draft and surface error.
        pildb.mark_draft_failed(
            _proforma_db_path(), batch_id, cn,
            notes=f"{type(exc).__name__}: {exc}"[:500],
        )
        return JSONResponse({
            "ok":          False,
            "status":      "failed",
            "batch_id":    batch_id,
            "client_name": cn,
            "draft_id":    draft.id,
            "error":       f"{type(exc).__name__}: {exc}",
        })

    if not result.ok:
        pildb.mark_draft_failed(
            _proforma_db_path(), batch_id, cn,
            notes=(result.error or "wfirma create_proforma_draft returned ok=false")[:500],
        )
        return JSONResponse({
            "ok":          False,
            "status":      "failed",
            "batch_id":    batch_id,
            "client_name": cn,
            "draft_id":    draft.id,
            "error":       result.error or "unknown",
        })

    # ── 6. Success: mark issued, persist wfirma_proforma_id ────────────────
    pildb.mark_draft_issued(
        _proforma_db_path(), batch_id, cn,
        wfirma_proforma_id=result.wfirma_invoice_id or "",
    )
    final = pildb.get_draft(_proforma_db_path(), batch_id, cn)
    return JSONResponse({
        "ok":                  True,
        "status":              "issued",
        "batch_id":            batch_id,
        "client_name":         cn,
        "draft_id":            final.id if final else draft.id,
        "wfirma_proforma_id":  result.wfirma_invoice_id,
        "currency":            (final or draft).currency,
        "exchange_rate":       (final or draft).exchange_rate,
    })


# ── Cancel-issued-for-reissue ───────────────────────────────────────────────
#
# Deletes a wrong-payload proforma from wFirma and resets the local draft
# to failed/retryable so the create route can issue a corrected payload.
# The wFirma delete MUST succeed before the local row is changed — if the
# delete fails the local draft remains 'issued' so no data is lost.

@router.post("/cancel-issued-for-reissue/{batch_id}/{client_name:path}",
             dependencies=[_auth])
def cancel_issued_proforma_for_reissue(
    batch_id:    str,
    client_name: str,
    confirm:     str = "",
) -> JSONResponse:
    """
    Cancel an issued wFirma proforma and reset the local draft to
    failed/retryable. Intended for cancel+reissue of wrong-payload or
    partial-line proformas (e.g. PROF 92/2026 — 1 line instead of 12,
    wrong vat_code).

    Guards (in order):
      1. WFIRMA_DELETE_INVOICE_ALLOWED=true
      2. confirm == "YES_DELETE_AND_REISSUE_ONE_PROFORMA"
      3. Local draft status must be "issued"
      4. wfirma_proforma_id must be present on the draft
      5. wFirma delete must return OK before the local row is changed
    """
    cn = _norm(client_name)

    # ── 1. Settings gate ───────────────────────────────────────────────────
    if not settings.wfirma_delete_invoice_allowed:
        return JSONResponse({
            "ok":               False,
            "status":           "blocked",
            "batch_id":         batch_id,
            "client_name":      cn,
            "blocking_reasons": ["WFIRMA_DELETE_INVOICE_ALLOWED=false — "
                                 "enable to proceed"],
        })

    # ── 2. Explicit confirmation string ────────────────────────────────────
    if confirm != "YES_DELETE_AND_REISSUE_ONE_PROFORMA":
        return JSONResponse({
            "ok":               False,
            "status":           "blocked",
            "batch_id":         batch_id,
            "client_name":      cn,
            "blocking_reasons": ["confirm string missing or wrong — "
                                 "must be YES_DELETE_AND_REISSUE_ONE_PROFORMA"],
        })

    # ── 3 + 4. Local draft state ────────────────────────────────────────────
    existing = pildb.get_draft(_proforma_db_path(), batch_id, cn)
    if existing is None:
        return JSONResponse({
            "ok":               False,
            "status":           "blocked",
            "batch_id":         batch_id,
            "client_name":      cn,
            "blocking_reasons": ["no local draft found for this batch/client"],
        })
    if existing.status != "issued":
        return JSONResponse({
            "ok":               False,
            "status":           "blocked",
            "batch_id":         batch_id,
            "client_name":      cn,
            "blocking_reasons": [
                f"draft status is {existing.status!r} — must be 'issued' "
                "to cancel"
            ],
        })
    wfirma_id = (existing.wfirma_proforma_id or "").strip()
    if not wfirma_id:
        return JSONResponse({
            "ok":               False,
            "status":           "blocked",
            "batch_id":         batch_id,
            "client_name":      cn,
            "blocking_reasons": ["wfirma_proforma_id is missing on draft — "
                                 "cannot identify which invoice to delete"],
        })

    # ── 5. wFirma delete — local row untouched until this returns OK ────────
    try:
        wfirma_client.delete_invoice(wfirma_id)
    except Exception as exc:
        return JSONResponse({
            "ok":                 False,
            "status":             "failed",
            "batch_id":           batch_id,
            "client_name":        cn,
            "wfirma_proforma_id": wfirma_id,
            "error": (
                f"wFirma delete failed — local draft unchanged: "
                f"{type(exc).__name__}: {exc}"
            ),
        })

    # Confirmed delete — now reset local row.
    try:
        pildb.mark_draft_cancelled_for_reissue(
            _proforma_db_path(), batch_id, cn,
            deleted_wfirma_id=wfirma_id,
            reason="cancel-issued-for-reissue endpoint",
        )
    except Exception as exc:
        log.error(
            "delete_invoice ok but local reset failed batch=%s client=%s "
            "wfirma_id=%s err=%s", batch_id, cn, wfirma_id, exc,
        )
        return JSONResponse({
            "ok":                 False,
            "status":             "failed",
            "batch_id":           batch_id,
            "client_name":        cn,
            "wfirma_proforma_id": wfirma_id,
            "error": (
                f"wFirma delete succeeded (id={wfirma_id}) but local reset "
                f"failed: {type(exc).__name__}: {exc} — "
                "proforma is gone from wFirma; create can be retried manually"
            ),
        })

    return JSONResponse({
        "ok":                True,
        "status":            "cancelled_for_reissue",
        "batch_id":          batch_id,
        "client_name":       cn,
        "deleted_wfirma_id": wfirma_id,
        "local_status":      "failed",
        "next_step":         (
            f"POST /api/v1/proforma/create/{batch_id}/{client_name} "
            "to reissue with corrected payload"
        ),
    })


# ── Adopt an existing wFirma proforma into local draft tracking ──────────────
#
# Used when an old proforma was issued before local draft tracking was added.
# Registers the wFirma id locally as status='issued' so cancel-issued-for-
# reissue can run against it. Does NOT make any wFirma writes.

from pydantic import BaseModel as _BaseModel  # noqa: E402 — localised import


class _AdoptIssuedBody(_BaseModel):
    wfirma_proforma_id: str
    reason: str


@router.post("/adopt-issued/{batch_id}/{client_name:path}", dependencies=[_auth])
def adopt_issued_proforma(
    batch_id:    str,
    client_name: str,
    body:        _AdoptIssuedBody,
) -> JSONResponse:
    """
    Register an existing wFirma proforma that predates local draft tracking.

    Behaviour:
      • Fetches the invoice XML to confirm type=proforma and id match.
      • Optionally verifies contractor id against local wfirma_customers mapping
        (warns if no mapping found; blocks if mapping present but contractor
        id mismatches).
      • Idempotent if called twice with the same wfirma_proforma_id.
      • Blocks if a different issued proforma is already registered locally.
      • No wFirma writes, no financial field changes.
    """
    cn              = _norm(client_name)
    wfirma_id_body  = (body.wfirma_proforma_id or "").strip()
    reason          = (body.reason or "").strip()

    if not wfirma_id_body:
        return JSONResponse({"ok": False, "status": "blocked",
                             "blocking_reasons": ["wfirma_proforma_id is required"]})
    if not reason:
        return JSONResponse({"ok": False, "status": "blocked",
                             "blocking_reasons": ["reason is required"]})

    # ── Fetch invoice XML ─────────────────────────────────────────────────────
    try:
        invoice_xml = wfirma_client.fetch_invoice_xml(wfirma_id_body)
    except Exception as exc:
        return JSONResponse({
            "ok":     False,
            "status": "blocked",
            "error":  f"wFirma XML fetch failed: {type(exc).__name__}: {exc}",
        })

    # ── Verify type=proforma ──────────────────────────────────────────────────
    try:
        root = ET.fromstring(invoice_xml)
    except ET.ParseError as exc:
        return JSONResponse({
            "ok":     False,
            "status": "blocked",
            "error":  f"wFirma returned invalid XML: {exc}",
        })

    invoice_node = root.find(".//invoice")
    if invoice_node is None:
        return JSONResponse({
            "ok":     False,
            "status": "blocked",
            "error":  "wFirma XML has no <invoice> element",
        })
    invoice_type = (invoice_node.findtext("type") or "").strip().lower()
    if invoice_type != "proforma":
        return JSONResponse({
            "ok":     False,
            "status": "blocked",
            "error":  f"wFirma document type is {invoice_type!r}, expected 'proforma'",
        })

    # ── Verify id matches body ────────────────────────────────────────────────
    fetched_id = (invoice_node.findtext("id") or "").strip()
    if fetched_id and fetched_id != wfirma_id_body:
        return JSONResponse({
            "ok":     False,
            "status": "blocked",
            "error":  (
                f"wFirma returned invoice id={fetched_id!r} but body "
                f"wfirma_proforma_id={wfirma_id_body!r} — id mismatch"
            ),
        })

    # ── Contractor verification ───────────────────────────────────────────────
    contractor_warn = None
    cust = wfdb.get_customer(cn) if wfdb._db_path is not None else None
    if cust and cust.get("wfirma_customer_id"):
        expected_contractor_id = str(cust["wfirma_customer_id"]).strip()
        contractor_node        = invoice_node.find(".//contractor")
        fetched_contractor_id  = ""
        if contractor_node is not None:
            fetched_contractor_id = (contractor_node.findtext("id") or "").strip()
        if fetched_contractor_id and fetched_contractor_id != expected_contractor_id:
            return JSONResponse({
                "ok":     False,
                "status": "blocked",
                "error":  (
                    f"contractor id mismatch: wFirma returned {fetched_contractor_id!r}, "
                    f"local mapping expects {expected_contractor_id!r} for {cn!r}"
                ),
            })
        if not fetched_contractor_id:
            contractor_warn = "contractor id absent in XML — could not verify"
    else:
        contractor_warn = (
            f"no wfirma_customers mapping for {cn!r} — contractor not verified"
        )

    # ── Adopt locally ─────────────────────────────────────────────────────────
    try:
        draft, was_created = pildb.adopt_issued_draft(
            _proforma_db_path(), batch_id, cn,
            wfirma_proforma_id=wfirma_id_body,
            reason=reason,
        )
    except ValueError as exc:
        return JSONResponse({
            "ok":     False,
            "status": "blocked",
            "error":  str(exc),
        })

    result: Dict[str, Any] = {
        "ok":                  True,
        "status":              "adopted" if was_created else "already_adopted",
        "batch_id":            batch_id,
        "client_name":         cn,
        "wfirma_proforma_id":  wfirma_id_body,
        "local_status":        draft.status,
        "was_created":         was_created,
        "next_step": (
            f"POST /api/v1/proforma/cancel-issued-for-reissue/{batch_id}/{client_name} "
            "to delete from wFirma and reset for reissue"
        ),
    }
    if contractor_warn:
        result["contractor_warning"] = contractor_warn
    return JSONResponse(result)


# ── Refresh proforma line names from locked description blocks ──────────────
#
# Operator-approved per-call. wFirma freezes invoicecontent <name> at issue
# time; the only way to bring an existing proforma's line names in sync with
# the current product master description_line is to POST a full-line restate
# to /invoices/edit/{invoice_id}. Live diagnostic 2026-05-06 confirmed:
#   - partial line edits are rejected (NOT_FOUND)
#   - header edits succeed
#   - full-line restate (only <name> changed) succeeds
#
# This route never deletes/reissues the proforma, never touches contractor /
# currency / quantity / price / VAT, never updates local DB rows, and never
# converts the proforma to a final invoice.

def _build_wfirma_id_to_code_map() -> Dict[str, str]:
    """{wfirma_product_id → product_code} from wfirma_products."""
    out: Dict[str, str] = {}
    if wfdb._db_path is None:
        return out
    for row in wfdb.list_products():
        wid = (row.get("wfirma_product_id") or "").strip()
        pc  = (row.get("product_code")      or "").strip()
        if wid and pc:
            out[wid] = pc
    return out


def _resolve_correct_line_name(product_code: str) -> Optional[str]:
    """Return the locked description_line for a product_code, or None."""
    if not product_code or ddb._db_path is None:
        return None
    row = ddb.get_product_description(product_code)
    if not row:
        return None
    return (row.get("description_line") or "").strip() or None


@router.post("/{wfirma_id}/refresh-line-names", dependencies=[_auth])
def proforma_refresh_line_names(wfirma_id: str) -> JSONResponse:
    """
    Refresh existing wFirma proforma line names from the locked product
    descriptions. Operator-approved per call. One proforma id per call.

    Status values:
      blocked  — settings gate off, OR id is not a proforma, OR a required
                 product mapping is missing for some line (refusal to start
                 a partial refresh)
      ok       — all stale lines were updated successfully
      partial  — some line edits failed at wFirma (per-line errors reported)
    """
    if not (wfirma_id or "").strip():
        raise HTTPException(status_code=400, detail="wfirma_id is required")

    # Settings gate — no live call when disabled.
    if not settings.wfirma_edit_invoice_allowed:
        return JSONResponse({
            "ok":               False,
            "status":           "blocked",
            "wfirma_id":        wfirma_id,
            "blocking_reasons": ["wfirma invoice edit disabled "
                                 "(WFIRMA_EDIT_INVOICE_ALLOWED=false)"],
        })

    # Fetch + verify type=proforma BEFORE any edit.
    try:
        invoice_xml = wfirma_client.fetch_invoice_xml(wfirma_id)
    except (RuntimeError, ValueError, ConnectionError) as exc:
        return JSONResponse({
            "ok":               False,
            "status":           "blocked",
            "wfirma_id":        wfirma_id,
            "blocking_reasons": [f"fetch failed: {type(exc).__name__}: {exc}"],
        })

    root = ET.fromstring(invoice_xml)
    invoice = root.find(".//invoice")
    if invoice is None:
        return JSONResponse({
            "ok":               False,
            "status":           "blocked",
            "wfirma_id":        wfirma_id,
            "blocking_reasons": ["invoices/find returned no <invoice>"],
        })

    invoice_type = (invoice.findtext("type") or "").strip().lower()
    if invoice_type != "proforma":
        return JSONResponse({
            "ok":               False,
            "status":           "blocked",
            "wfirma_id":        wfirma_id,
            "blocking_reasons": [f"invoice type={invoice_type!r} — refusing "
                                 "edits on non-proforma documents"],
        })

    contents = invoice.find("invoicecontents")
    lines = list(contents.findall("invoicecontent")) if contents is not None else []
    if not lines:
        return JSONResponse({
            "ok":        True,
            "status":    "ok",
            "wfirma_id": wfirma_id,
            "checked":   0,
            "updated":   0,
            "skipped":   0,
            "errors":    [],
            "lines":     [],
        })

    # ── Resolve all mappings BEFORE any edit. Refuse to start if any
    #    line lacks a good/id or product_code mapping (avoids partial drift).
    id_to_code = _build_wfirma_id_to_code_map()

    plan: List[Dict[str, Any]] = []
    setup_errors: List[Dict[str, Any]] = []
    for ic in lines:
        line_id      = (ic.findtext("id") or "").strip()
        current_name = (ic.findtext("name") or "").strip()
        good_id      = ""
        good_node    = ic.find("good")
        if good_node is not None:
            good_id = (good_node.findtext("id") or "").strip()

        if not line_id:
            setup_errors.append({"line_id": line_id, "error": "missing invoicecontent <id>"})
            continue
        if not good_id:
            setup_errors.append({
                "line_id": line_id, "good_id": "", "current_name": current_name,
                "error":   "missing <good><id> on invoicecontent — cannot resolve product",
            })
            continue
        product_code = id_to_code.get(good_id, "")
        if not product_code:
            setup_errors.append({
                "line_id": line_id, "good_id": good_id, "current_name": current_name,
                "error": (
                    f"no wfirma_products row maps wfirma_product_id={good_id!r} "
                    "to a local product_code"
                ),
            })
            continue
        correct_name = _resolve_correct_line_name(product_code)
        if not correct_name:
            setup_errors.append({
                "line_id": line_id, "good_id": good_id, "product_code": product_code,
                "current_name": current_name,
                "error": (
                    f"no product_descriptions row with description_line for "
                    f"product_code={product_code!r}"
                ),
            })
            continue
        plan.append({
            "line_id":       line_id,
            "good_id":       good_id,
            "product_code":  product_code,
            "current_name":  current_name,
            "correct_name":  correct_name,
            "ic_xml":        ET.tostring(ic, encoding="unicode"),
        })

    if setup_errors:
        return JSONResponse({
            "ok":               False,
            "status":           "blocked",
            "wfirma_id":        wfirma_id,
            "blocking_reasons": [
                f"{len(setup_errors)} line(s) missing required mappings — "
                "refusing partial refresh"
            ],
            "errors": setup_errors,
        })

    # ── Execute edits. Skip lines already at the correct name. ──────────────
    checked = len(plan)
    updated = 0
    skipped = 0
    line_results: List[Dict[str, Any]] = []
    edit_errors: List[Dict[str, Any]]  = []

    for entry in plan:
        if entry["current_name"] == entry["correct_name"]:
            skipped += 1
            line_results.append({
                "line_id":      entry["line_id"],
                "product_code": entry["product_code"],
                "status":       "already_correct",
                "name":         entry["current_name"],
            })
            continue
        try:
            wfirma_client.edit_invoice_line_name(
                wfirma_id, entry["ic_xml"], entry["correct_name"],
            )
            updated += 1
            line_results.append({
                "line_id":      entry["line_id"],
                "product_code": entry["product_code"],
                "status":       "updated",
                "old_name":     entry["current_name"],
                "new_name":     entry["correct_name"],
            })
        except Exception as exc:
            edit_errors.append({
                "line_id":      entry["line_id"],
                "product_code": entry["product_code"],
                "current_name": entry["current_name"],
                "correct_name": entry["correct_name"],
                "error":        f"{type(exc).__name__}: {exc}",
            })
            line_results.append({
                "line_id":      entry["line_id"],
                "product_code": entry["product_code"],
                "status":       "failed",
                "error":        f"{type(exc).__name__}: {exc}",
            })

    # ── Verify-after-edit: re-fetch and confirm each updated line ──────────
    # wFirma returned status=OK on each edit, but a final re-fetch closes
    # the loop — if any persisted name does not match what we sent, the
    # edit silently no-op'd and the route must surface that as a hard
    # failed_verification rather than green status=ok.
    verify_errors: List[Dict[str, Any]] = []
    if updated > 0 and not edit_errors:
        try:
            verify_xml  = wfirma_client.fetch_invoice_xml(wfirma_id)
            verify_root = ET.fromstring(verify_xml)
            actual_by_id: Dict[str, str] = {}
            for ic in verify_root.iter("invoicecontent"):
                lid = (ic.findtext("id") or "").strip()
                if lid:
                    actual_by_id[lid] = (ic.findtext("name") or "").strip()
            for entry in plan:
                if entry["current_name"] == entry["correct_name"]:
                    continue  # not edited; skipped above
                actual = actual_by_id.get(entry["line_id"], "")
                if actual != entry["correct_name"]:
                    verify_errors.append({
                        "line_id":      entry["line_id"],
                        "product_code": entry["product_code"],
                        "expected":     entry["correct_name"],
                        "actual":       actual,
                    })
        except Exception as exc:
            verify_errors.append({
                "line_id":  "",
                "error":    f"verify fetch failed: {type(exc).__name__}: {exc}",
            })

    if edit_errors:
        overall_status = "partial"
    elif verify_errors:
        overall_status = "failed_verification"
    else:
        overall_status = "ok"

    return JSONResponse({
        "ok":             not edit_errors and not verify_errors,
        "status":         overall_status,
        "wfirma_id":      wfirma_id,
        "checked":        checked,
        "updated":        updated,
        "skipped":        skipped,
        "errors":         edit_errors,
        "verify_errors":  verify_errors,
        "lines":          line_results,
    })


# ── Proforma Document (read-only view) ────────────────────────────────────────

def _parse_proforma_from_xml(xml_text: str) -> dict:
    """
    Parse a wFirma invoices/find response into a structured proforma summary.

    Returns: invoice_type, full_number, date, contractor_id, currency, lines.
    Lines: name, quantity, unit_price, total_net, vat_rate.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return {}

    inv = root.find(".//invoice")
    if inv is None:
        return {}

    def _txt(*path):
        node = inv
        for tag in path:
            if node is None:
                return ""
            node = node.find(tag)
        return (node.text or "").strip() if node is not None else ""

    invoice_type  = _txt("type") or _txt("invoice_type") or ""
    full_number   = _txt("full_number") or _txt("number") or ""
    date          = _txt("date") or _txt("invoice_date") or ""
    contractor_id = _txt("contractor", "id") or _txt("contractor_id") or ""
    currency      = _txt("currency") or "PLN"
    status        = _txt("status") or ""

    lines: List[dict] = []
    for ic in root.findall(".//invoicecontent"):
        def _ctxt(*path):
            node = ic
            for tag in path:
                if node is None:
                    return ""
                node = node.find(tag)
            return (node.text or "").strip() if node is not None else ""

        name = _ctxt("name") or ""
        try:
            qty = float(_ctxt("count") or _ctxt("quantity") or 1)
        except (TypeError, ValueError):
            qty = 1.0
        try:
            unit_price = float(_ctxt("price_netto") or _ctxt("unit_price") or 0)
        except (TypeError, ValueError):
            unit_price = 0.0
        try:
            total_net = float(_ctxt("netto") or _ctxt("total_netto") or 0)
        except (TypeError, ValueError):
            total_net = 0.0
        vat_rate = _ctxt("vat", "code") or _ctxt("vat_code") or ""

        lines.append({
            "name":       name,
            "quantity":   qty,
            "unit_price": unit_price,
            "total_net":  total_net,
            "vat_rate":   vat_rate,
        })

    return {
        "invoice_type":  invoice_type,
        "full_number":   full_number,
        "date":          date,
        "contractor_id": contractor_id,
        "currency":      currency,
        "status":        status,
        "lines":         lines,
    }


@router.get("/{batch_id}/{client_name:path}/document", dependencies=[_auth])
async def proforma_document(batch_id: str, client_name: str) -> JSONResponse:
    """
    Read-only view of the linked wFirma proforma invoice.

    Reads the wfirma_proforma_id from the proforma_drafts table, fetches the
    invoice XML from wFirma, and returns structured JSON with header + lines.

    Blocks if invoice_type is not 'proforma' (safety guard against viewing
    regular invoices via this endpoint).

    No writes are performed.

    Response fields
    ---------------
    batch_id          echoed
    client_name       echoed
    wfirma_proforma_id  wFirma invoice ID
    invoice_type      must be 'proforma'
    full_number       human-readable invoice number
    date              invoice date
    contractor_id     wFirma contractor (customer) ID
    currency          invoice currency
    status            wFirma document status
    line_count        number of invoice lines
    lines             list of {name, quantity, unit_price, total_net, vat_rate}
    raw_xml           raw wFirma XML response (for diagnostics)
    """
    cn = (client_name or "").strip()
    if not cn:
        raise HTTPException(status_code=400, detail="client_name is required")

    db_path = _proforma_db_path()
    draft   = pildb.get_draft(db_path, batch_id, cn)

    if draft is None or not (draft.wfirma_proforma_id or "").strip():
        raise HTTPException(
            status_code=404,
            detail={
                "error":      "No proforma linked to this shipment/client.",
                "code":       "PROFORMA_NOT_LINKED",
                "batch_id":   batch_id,
                "client_name": cn,
            },
        )

    wfirma_id = draft.wfirma_proforma_id.strip()

    try:
        xml_text = wfirma_client.fetch_invoice_xml(wfirma_id)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error":    f"wFirma fetch failed: {exc}",
                "code":     "PROFORMA_FETCH_FAILED",
                "batch_id": batch_id,
                "wfirma_proforma_id": wfirma_id,
            },
        )

    parsed = _parse_proforma_from_xml(xml_text)

    # Safety: reject if wFirma says this is not a proforma
    invoice_type = (parsed.get("invoice_type") or "").lower()
    if invoice_type and invoice_type != "proforma":
        log.warning(
            "[%s/%s] proforma_document: wFirma id %s is type=%r, not proforma",
            batch_id, cn, wfirma_id, invoice_type,
        )
        raise HTTPException(
            status_code=409,
            detail={
                "error":        f"Document {wfirma_id!r} is type {invoice_type!r}, not proforma.",
                "code":         "NOT_A_PROFORMA",
                "batch_id":     batch_id,
                "wfirma_id":    wfirma_id,
                "invoice_type": invoice_type,
            },
        )

    log.info(
        "[%s/%s] proforma_document: fetched proforma %s (%d lines)",
        batch_id, cn, wfirma_id, len(parsed.get("lines", [])),
    )

    return JSONResponse({
        "batch_id":           batch_id,
        "client_name":        cn,
        "wfirma_proforma_id": wfirma_id,
        "invoice_type":       parsed.get("invoice_type", ""),
        "full_number":        parsed.get("full_number", ""),
        "date":               parsed.get("date", ""),
        "contractor_id":      parsed.get("contractor_id", ""),
        "currency":           parsed.get("currency", "PLN"),
        "status":             parsed.get("status", ""),
        "line_count":         len(parsed.get("lines", [])),
        "lines":              parsed.get("lines", []),
        "raw_xml":            xml_text,
    })
