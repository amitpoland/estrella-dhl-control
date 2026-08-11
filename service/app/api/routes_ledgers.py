"""
routes_ledgers.py — Phase 10A invoice-ledger endpoint.
=====================================================

GET /api/v1/ledgers/clients/{contractor_id}/invoice-ledger.json
    ?from=YYYY-MM-DD&to=YYYY-MM-DD

Read-only. Returns a chronological per-currency list of invoices
issued to the given wFirma contractor in the requested window.

This endpoint is INTENTIONALLY named ``invoice-ledger`` — NOT
``statement``. A full Statement of Account requires payment data
(``alreadypaid`` / ``remaining`` / ``paymentstate`` / aging buckets)
that has not yet been verified against a live wFirma response.

# TODO Phase 10A.5 — REQUIRED before any Statement / Aging work.
#
# Add a read-only operator-run probe under app/tools/:
#   probe_payments_and_invoice_payment_state.py
#
# It must:
#   1. Call invoices/find with the smallest filter that returns one
#      <invoice> node, dump the response XML, and enumerate every leaf
#      tag — confirming presence/absence of <alreadypaid>, <remaining>,
#      <paymentstate>, <paymentdate>, <paid_date>.
#   2. Call payments/find with no filters (then start=0&limit=1) and
#      dump the response — confirming the request shape is accepted
#      and enumerating response fields (<value>, <date>, <method>,
#      <invoice><id>, <contractor><id>?).
#   3. Call payments/find with each plausible filter
#      (contractor_id / invoice_id / date / paymentdate) one at a time,
#      capture wFirma's status code + description.
#   4. Output a Markdown evidence document — committed to the repo so
#      Phase 10B has verified field/filter contracts to build on.
#
# The probe MUST NOT commit dumped XML (real customer data); only the
# field/filter availability summary.
"""
from __future__ import annotations

import time
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

from ..core.logging import get_logger
from ..core.security import require_api_key
from ..services import wfirma_client
from ..services.customer_master_db import (    # C-2b V5 reroute
    lookup_wfirma_contractor as _cmd_lookup_contractor,
)
from ..services.ledger_aggregator import (
    aggregate_invoice_ledger,
    aggregate_statement,
    aggregate_supplier_statement,
    _parse_expense_fact,
    _parse_payment_fact,
)


log    = get_logger(__name__)
router = APIRouter(prefix="/api/v1/ledgers", tags=["ledgers"])
_auth  = Depends(require_api_key)


# ── Helpers ────────────────────────────────────────────────────────────────

_DATE_LEN = len("YYYY-MM-DD")


def _utc_quarter_start(today: str) -> str:
    """Calendar-quarter start (UTC) for cold-path default ledger window."""
    y = int(today[:4])
    m = int(today[5:7])
    q = ((m - 1) // 3) * 3 + 1
    return f"{y}-{q:02d}-01"


def _validate_date(label: str, value: str) -> str:
    """Defensive ISO-date check. We do not parse via datetime.fromisoformat
    because we accept only the ``YYYY-MM-DD`` shape (no time component,
    no offset) — wFirma's filter values are date-only."""
    s = (value or "").strip()
    if len(s) != _DATE_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"{label} must be YYYY-MM-DD, got {value!r}",
        )
    if s[4] != "-" or s[7] != "-":
        raise HTTPException(
            status_code=400,
            detail=f"{label} must be YYYY-MM-DD, got {value!r}",
        )
    if not (s[:4].isdigit() and s[5:7].isdigit() and s[8:10].isdigit()):
        raise HTTPException(
            status_code=400,
            detail=f"{label} must be YYYY-MM-DD, got {value!r}",
        )
    return s


def _utc_today() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _outstanding_floor() -> str:
    """Configured lookback floor for ``scope=all_outstanding``.

    A misconfigured floor is an operator/env error, not a client error, so it
    surfaces as 500 rather than a 400 blamed on the request.
    """
    from ..core.config import settings as _settings

    raw = (getattr(_settings, "ledger_outstanding_floor", "") or "").strip()
    try:
        return _validate_date("ledger_outstanding_floor", raw)
    except HTTPException as exc:
        raise HTTPException(
            status_code=500,
            detail=f"LEDGER_OUTSTANDING_FLOOR must be YYYY-MM-DD, got {raw!r}",
        ) from exc


def _resolve_analysis_window(scope: str, from_: str, to: str, as_of: str):
    """Resolve the (from, to, as_of, scope) window for the analysis routes.

    ``scope`` empty or ``custom_period`` → unchanged legacy contract: from/to
    are required and the 400 behaviour is byte-identical, including the order
    in which the validations fire.

    ``scope=all_outstanding`` → the full open portfolio: ``from`` defaults to
    the configured floor and ``to`` defaults to ``as_of``. Management
    outstanding is a balance-sheet-style current exposure, not "documents
    issued this month", so this is the default the UI opens on.

    Returns ``(df, dt, ao, resolved_scope)``.
    """
    sc = (scope or "").strip().lower()
    if sc and sc not in ("all_outstanding", "custom_period"):
        raise HTTPException(
            status_code=400,
            detail="scope must be all_outstanding, custom_period, or empty",
        )
    if sc == "all_outstanding":
        ao = _validate_date("as_of", as_of) if (as_of or "").strip() else _utc_today()
        df = _validate_date("from", from_) if (from_ or "").strip() else _outstanding_floor()
        dt = _validate_date("to", to) if (to or "").strip() else ao
        if df > dt:
            raise HTTPException(status_code=400, detail=f"from {df!r} is after to {dt!r}")
        return df, dt, ao, sc
    df = _validate_date("from", from_)
    dt = _validate_date("to", to)
    if df > dt:
        raise HTTPException(status_code=400, detail=f"from {df!r} is after to {dt!r}")
    ao = _validate_date("as_of", as_of) if (as_of or "").strip() else _utc_today()
    return df, dt, ao, (sc or "custom_period")


def _python_side_date_filter(invoice_nodes, df: str, dt: str):
    """wFirma's ``<date>`` filter is documented but historically fragile
    — ``wfirma_client.fetch_invoices_for_contractor`` explicitly delegates
    final date enforcement to the caller. We re-filter here so an
    invoice that wFirma silently returned out of window is dropped
    before it reaches the aggregator.

    Empty ``date`` on an invoice → kept (we have no way to compare; we
    let the aggregator surface it). Comparison is lexicographic on the
    YYYY-MM-DD string, which matches calendar order for that format.
    """
    if not (df or dt):
        return list(invoice_nodes)
    out = []
    for inv in invoice_nodes:
        d = (inv.findtext("date") or "").strip()
        if not d:
            out.append(inv)
            continue
        if df and d < df:
            continue
        if dt and d > dt:
            continue
        out.append(inv)
    return out


# ── Endpoint ───────────────────────────────────────────────────────────────

@router.get(
    "/clients/{contractor_id}/invoice-ledger.json",
    dependencies=[_auth],
)
def get_client_invoice_ledger(
    contractor_id: str,
    from_:         str = Query("", alias="from",
                                description="Window start, YYYY-MM-DD"),
    to:            str = Query("",
                                description="Window end, YYYY-MM-DD"),
) -> JSONResponse:
    """Read-only invoice ledger for one wFirma contractor.

    Query params (operator URL):
      ?from=YYYY-MM-DD&to=YYYY-MM-DD   (both required, both inclusive)

    Outcomes:
      200  — JSON ledger (empty list per currency when no matches)
      400  — invalid contractor id, invalid date, ``from > to``
      404  — contractor not found in wFirma
      502  — wFirma fetch failed (HTTP / parse / non-OK status)
    """
    cid = (contractor_id or "").strip()
    if not cid:
        raise HTTPException(status_code=400, detail="contractor_id is required")
    if "/" in cid or ".." in cid:
        raise HTTPException(status_code=400, detail="invalid contractor_id")
    df = _validate_date("from", from_)
    dt = _validate_date("to",   to)
    if df > dt:
        raise HTTPException(
            status_code=400,
            detail=f"from {df!r} is after to {dt!r}",
        )

    # Preflight: confirm contractor exists. Same pattern as the Phase 5
    # /post receiver-preflight.
    try:
        rcv = _cmd_lookup_contractor(cid)  # C-2b V5
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error": f"wFirma contractor preflight failed: {exc}",
                "code":  "LEDGER_PREFLIGHT_FAILED",
                "wfirma_contractor_id": cid,
            },
        )
    if not rcv.ok:
        raise HTTPException(
            status_code=404,
            detail={
                "error": rcv.error or "contractor not found",
                "code":  "CONTRACTOR_NOT_FOUND",
                "wfirma_contractor_id": cid,
            },
        )

    contractor_meta = {
        "wfirma_contractor_id": cid,
        "name":     getattr(rcv, "name",    "") or "",
        "country":  getattr(rcv, "country", "") or "",
        "vat_id":   getattr(rcv, "nip",     "") or "",
    }

    try:
        from ..services.ledger_fact_universe import FISCAL_AR_INVOICE_TYPES
        nodes = wfirma_client.fetch_invoices_for_contractor(
            cid, df, dt,
            types=FISCAL_AR_INVOICE_TYPES,
        )
    except Exception as exc:
        log.warning(
            "[ledger %s] fetch_invoices_for_contractor failed: %s",
            cid, exc,
        )
        raise HTTPException(
            status_code=502,
            detail={
                "error": f"wFirma invoices/find failed: {exc}",
                "code":  "LEDGER_FETCH_FAILED",
                "wfirma_contractor_id": cid,
            },
        )

    # Defence-in-depth Python-side date filter — wFirma is known to
    # silently ignore unsupported filter shapes.
    nodes = _python_side_date_filter(nodes, df, dt)

    body = aggregate_invoice_ledger(
        contractor_meta = contractor_meta,
        invoice_nodes   = nodes,
        period          = (df, dt),
    )
    return JSONResponse(body)


# ── Phase 10B — Statement of Account ───────────────────────────────────────
#
# Distinct from /invoice-ledger.json (Phase 10A): the Statement
# combines invoices + payments, computes per-invoice remaining via
# payments-driven reconciliation, and emits per-currency totals +
# aging buckets. Architecture pinned by
# ``docs/PHASE10B_STATEMENT_ARCHITECTURE.md``.
#
# Aging authority (2026-08-10): default ``due_date`` = invoice
# ``paymentdate``, same canonical basis as Management Analysis (100%
# open coverage on live probe). ``invoice_age`` only when the caller
# passes ``aging_method=invoice_age`` explicitly — no silent mix.


def _python_side_payment_date_filter(payment_nodes, df: str, dt: str):
    """Same defence-in-depth as ``_python_side_date_filter`` but on
    payment ``<date>``."""
    if not (df or dt):
        return list(payment_nodes)
    out = []
    for p in payment_nodes:
        d = (p.findtext("date") or "").strip()
        if not d:
            out.append(p)
            continue
        if df and d < df:
            continue
        if dt and d > dt:
            continue
        out.append(p)
    return out


def _normalize_statement_aging_method(raw: str) -> str:
    from ..services.ledger_aggregator import (
        AGING_METHOD_DUE_DATE,
        AGING_METHOD_INVOICE_AGE,
        _normalize_aging_method,
    )
    m = (raw or "").strip().lower()
    if m and m not in (AGING_METHOD_DUE_DATE, AGING_METHOD_INVOICE_AGE):
        raise HTTPException(
            status_code=400,
            detail="aging_method must be due_date, invoice_age, or empty",
        )
    return _normalize_aging_method(m)


def _contractor_meta_from_customer_master(cid: str, rcv) -> Dict[str, Any]:
    """Postal + identity for Statement: Customer Master first, wFirma
    preflight as fallback for name/country/VAT only."""
    from ..core.config import settings as _settings
    meta: Dict[str, Any] = {
        "wfirma_contractor_id": cid,
        "name":     getattr(rcv, "name",    "") or "",
        "country":  getattr(rcv, "country", "") or "",
        "vat_id":   getattr(rcv, "nip",     "") or "",
        "street":   "",
        "city":     "",
        "postal_code": "",
        "email":    "",
        "phone":    "",
    }
    try:
        from ..services.customer_master_db import get_customer
        cust = get_customer(_settings.storage_root / "customer_master.sqlite", cid)
    except Exception:
        cust = None
    if cust is None:
        return meta
    name = (getattr(cust, "bill_to_name", None) or "").strip()
    if name:
        meta["name"] = name
    country = (getattr(cust, "bill_to_country", None)
               or getattr(cust, "country", None) or "").strip()
    if country:
        meta["country"] = country
    vat = (getattr(cust, "vat_eu_number", None)
           or getattr(cust, "nip", None) or "").strip()
    if vat:
        meta["vat_id"] = vat
    meta["street"] = (getattr(cust, "bill_to_street", None) or "").strip()
    meta["city"] = (getattr(cust, "bill_to_city", None) or "").strip()
    meta["postal_code"] = (getattr(cust, "bill_to_postal_code", None) or "").strip()
    meta["email"] = (getattr(cust, "bill_to_email", None) or "").strip()
    meta["phone"] = (getattr(cust, "bill_to_phone", None) or "").strip()
    return meta


def _supplier_meta_from_master(cid: str, name_from_facts: str) -> Dict[str, Any]:
    """Identity + postal for the Supplier Statement — the AP mirror of
    :func:`_contractor_meta_from_customer_master`.

    The AP fact universe carries only the contractor name, so the address and
    tax id come from Supplier Master (local sqlite, zero wFirma calls). Missing
    db / row / column degrades to the fact name — the statement still renders,
    the PDF simply omits the address block.
    """
    from ..core.config import settings as _settings

    meta: Dict[str, Any] = {
        "wfirma_contractor_id": cid,
        "name": name_from_facts or cid,
        "country": "", "vat_id": "", "street": "", "city": "", "postal_code": "",
    }
    try:
        from ..services.suppliers_db import get_supplier_by_wfirma_id
        sup = get_supplier_by_wfirma_id(_settings.storage_root / "suppliers.sqlite", cid)
    except Exception:
        sup = None
    if sup is None:
        return meta
    # wFirma is the accounting authority for the name shown on AP documents;
    # Supplier Master only fills what the facts cannot provide.
    if not name_from_facts and (sup.name or "").strip():
        meta["name"] = sup.name.strip()
    meta["country"] = (sup.country or "").strip()
    meta["vat_id"] = (sup.vat_id or "").strip()
    meta["street"] = (sup.street or "").strip()
    meta["city"] = (sup.city or "").strip()
    meta["postal_code"] = (sup.postal_code or "").strip()
    return meta


def _facts_for_contractor(
    invoice_facts: list,
    payment_facts: list,
    cid: str,
) -> tuple:
    """Slice shared AR universe facts down to one contractor.

    Invoices: exact ``contractor_id`` match.
    Payments: same contractor_id OR linked to an in-slice invoice id
    (covers bulk payment rows that omit contractor but link a fiscal
    invoice in the window).
    """
    inv = [
        f for f in (invoice_facts or [])
        if (f.get("contractor_id") or "").strip() == cid
    ]
    inv_ids = {(f.get("id") or "").strip() for f in inv if f.get("id")}
    pay = []
    for f in payment_facts or []:
        pcid = (f.get("contractor_id") or "").strip()
        linked = (f.get("linked_invoice") or "").strip()
        if pcid == cid or (linked and linked in inv_ids):
            pay.append(f)
    return inv, pay


def _build_statement_dict(
    contractor_id: str,
    from_:         str,
    to:            str,
    as_of:         str,
    *,
    aging_method: str = "",
) -> Dict[str, Any]:
    """Shared builder used by BOTH ``/statement.json`` and
    ``/statement.pdf`` routes.

    Consumes the shared fiscal AR fact universe (#1172
    ``FISCAL_AR_INVOICE_TYPES`` via ``load_ar_fact_universe``) and the
    shared ``aggregate_statement_from_facts`` authority — Statement does
    NOT re-fetch a commercial type set or re-implement fiscal filtering.

    Raises ``HTTPException`` (400 / 404 / 502) on any failure. The PDF
    route inherits the same error shapes without duplication.

    Pure side-effects on wFirma: none. Read-only by construction.
    """
    from ..services.ledger_aggregator import aggregate_statement_from_facts
    from ..services.ledger_fact_universe import load_ar_fact_universe

    cid = (contractor_id or "").strip()
    if not cid:
        raise HTTPException(status_code=400, detail="contractor_id is required")
    if "/" in cid or ".." in cid:
        raise HTTPException(status_code=400, detail="invalid contractor_id")
    df = _validate_date("from", from_)
    dt = _validate_date("to",   to)
    if df > dt:
        raise HTTPException(
            status_code=400,
            detail=f"from {df!r} is after to {dt!r}",
        )

    if (as_of or "").strip():
        ao = _validate_date("as_of", as_of)
    else:
        from datetime import datetime, timezone
        ao = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if ao < df:
        raise HTTPException(
            status_code=400,
            detail=f"as_of {ao!r} is before from {df!r}",
        )

    method = _normalize_statement_aging_method(aging_method)

    # Preflight contractor.
    try:
        rcv = _cmd_lookup_contractor(cid)  # C-2b V5
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error": f"wFirma contractor preflight failed: {exc}",
                "code":  "STATEMENT_PREFLIGHT_FAILED",
                "wfirma_contractor_id": cid,
            },
        )
    if not rcv.ok:
        raise HTTPException(
            status_code=404,
            detail={
                "error": rcv.error or "contractor not found",
                "code":  "CONTRACTOR_NOT_FOUND",
                "wfirma_contractor_id": cid,
            },
        )

    contractor_meta = _contractor_meta_from_customer_master(cid, rcv)

    try:
        uni = load_ar_fact_universe(df, dt)
    except Exception as exc:
        log.warning(
            "[statement %s] load_ar_fact_universe failed: %s",
            cid, exc,
        )
        raise HTTPException(
            status_code=502,
            detail={
                "error": f"wFirma AR fact universe failed: {exc}",
                "code":  "STATEMENT_INVOICE_FETCH_FAILED",
                "wfirma_contractor_id": cid,
            },
        ) from exc

    invoice_facts, payment_facts = _facts_for_contractor(
        uni.get("invoice_facts") or [],
        uni.get("payment_facts") or [],
        cid,
    )

    return aggregate_statement_from_facts(
        contractor_meta,
        invoice_facts,
        payment_facts,
        ao,
        (df, dt),
        aging_method=method,
    )


@router.get(
    "/clients/{contractor_id}/statement.json",
    dependencies=[_auth],
)
def get_client_statement(
    contractor_id: str,
    from_:         str = Query("", alias="from",
                                description="Window start, YYYY-MM-DD"),
    to:            str = Query("",
                                description="Window end, YYYY-MM-DD"),
    as_of:         str = Query("",
                                description="Aging anchor date, YYYY-MM-DD; "
                                            "default = today UTC"),
    aging_method:  str = Query(
        "",
        description="Aging basis: due_date (default, paymentdate) or "
                    "invoice_age (explicit opt-in only)",
    ),
) -> JSONResponse:
    """Read-only Statement of Account for one wFirma contractor.

    Consumes the shared fiscal AR fact universe +
    ``aggregate_statement_from_facts`` (same authority as Client Balance /
    Management Analysis). Emits per-currency entries, totals, aging,
    unmatched payments, and internal warnings.

    Aging authority: default ``due_date`` (invoice ``paymentdate``).
    Pass ``aging_method=invoice_age`` only for an explicit invoice-age view.

    Outcomes:
      200  — JSON Statement (empty per-currency maps when no activity)
      400  — invalid contractor id, invalid date, ``from > to``,
              ``as_of < from``, invalid aging_method
      404  — contractor not found in wFirma
      502  — shared AR fact-universe load failed
    """
    body = _build_statement_dict(
        contractor_id, from_, to, as_of, aging_method=aging_method,
    )
    return JSONResponse(body)


# ── Phase 10C — Statement PDF ──────────────────────────────────────────────
#
# Pure renderer over the Phase 10B JSON model. The route reuses
# ``_build_statement_dict`` for validation + fetch + aggregation, then
# hands the dict to ``render_statement_pdf`` (which performs no I/O,
# no DB read, no wFirma round-trip).

from fastapi import Response   # noqa: E402  — kept here, route-local
from ..services.statement_pdf_renderer import (   # noqa: E402
    render_statement_pdf,
    render_supplier_statement_pdf,
    render_management_analysis_pdf,
)


def _safe_filename(value: str) -> str:
    """Sanitise a string for use in Content-Disposition's filename
    parameter. Replaces every char outside the alnum/. _- set with
    underscore."""
    return "".join(
        c if (c.isalnum() or c in "._-") else "_"
        for c in (value or "")
    )


@router.get(
    "/clients/{contractor_id}/statement.pdf",
    dependencies=[_auth],
)
def get_client_statement_pdf(
    contractor_id: str,
    from_:         str = Query("", alias="from",
                                description="Window start, YYYY-MM-DD"),
    to:            str = Query("",
                                description="Window end, YYYY-MM-DD"),
    as_of:         str = Query("",
                                description="Aging anchor date, YYYY-MM-DD; "
                                            "default = today UTC"),
    aging_method:  str = Query(
        "",
        description="Aging basis: due_date (default) or invoice_age",
    ),
) -> Response:
    """Read-only PDF rendering of the Statement of Account.

    Identical contract to ``/statement.json``: same validation, same
    shared fiscal universe, same aggregation. The PDF is rendered from
    the resulting dict — no second arithmetic path.

    Customer-facing presentation: omits wFirma ids, DQ warnings, and
    technical labels; reuses Company Profile seller footer + document
    logo asset when present.
    """
    statement = _build_statement_dict(
        contractor_id, from_, to, as_of, aging_method=aging_method,
    )

    seller = _statement_seller_block()
    logo_path = _statement_logo_path()

    try:
        pdf_bytes = render_statement_pdf(
            statement,
            customer_facing=True,
            seller=seller,
            logo_path=logo_path,
        )
    except Exception as exc:
        log.warning(
            "[statement-pdf %s] render_statement_pdf failed: %s",
            contractor_id, exc,
        )
        raise HTTPException(
            status_code=502,
            detail={
                "error": f"PDF render failed: {exc}",
                "code":  "STATEMENT_PDF_RENDER_FAILED",
                "wfirma_contractor_id": (contractor_id or "").strip(),
            },
        )

    safe_id = _safe_filename(contractor_id)
    filename = f"statement-{safe_id}-{from_}-{to}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


def _statement_seller_block() -> Dict[str, str]:
    """Reuse CompanyProfile (same seller authority as packing/proforma)."""
    from ..core.config import settings as _settings
    from ..services.master_data_db import get_company_profile
    from ..services.commercial_packing_list import _seller_from_company

    try:
        company = get_company_profile(_settings.storage_root / "master_data.sqlite")
    except Exception:
        company = None
    return _seller_from_company(company)


def _statement_logo_path() -> str:
    """Same asset path Proforma Document Suite uses (PNG preferred)."""
    from pathlib import Path
    base = Path(__file__).resolve().parents[1] / "static" / "v2" / "assets"
    for name in ("estrella-logo.png", "estrella-logo.jpg", "estrella-logo.jpeg"):
        p = base / name
        if p.is_file():
            return str(p)
    return ""


# ── Wave 4 Item 4 — Client Balance roster ──────────────────────────────────
#
# GET /api/v1/ledgers/clients
#
# Read-only roster: the Customer Master client list JOINed with per-client
# balance figures computed by REUSING the documented Statement authority
# (aggregate_statement over invoices/find + payments/find — same path as
# /clients/{id}/statement.json). No local balance mirror; balances are
# computed live per client and fault-isolated so one client's wFirma failure
# does not fail the whole roster.
#
# SPLIT (operator ruling 2026-07-05) — column authority status:
#   Open (outstanding)          DOCUMENTED  — totals_per_currency.outstanding
#   Currency / State            DOCUMENTED  — derived from the same totals
#   YTD (invoiced in period)    DOCUMENTED  — totals_per_currency.invoiced,
#                                             default window = year-to-date
#   Overdue (invoice-age)       DOCUMENTED  — aging total minus "current"
#                                             bucket (invoice_age basis)
#   Overdue (due-date)          BACKEND PENDING — blocked by the PHASE10A.5
#                                             payment-state probe (see top of
#                                             file); invoice-age substituted,
#                                             basis disclosed, never relabelled
#   Last 30d (rolling receipts) BACKEND PENDING — no existing authority emits
#                                             a rolling-window receipts figure
from datetime import datetime, timezone   # noqa: E402
from decimal import Decimal               # noqa: E402

from ..core.config import settings        # noqa: E402
from ..services.customer_master_db import (   # noqa: E402
    list_customers as _cm_list_customers,
)

_CM_DB_PATH = settings.storage_root / "customer_master.sqlite"


def _sum_ccy(m: Dict[str, Any]) -> Decimal:
    """Sum a {currency: numeric-string} map into a Decimal (bad values skipped)."""
    tot = Decimal("0")
    for v in m.values():
        try:
            tot += Decimal(str(v))
        except Exception:
            pass
    return tot


def _roster_row_from_statement(default_currency: str,
                               stmt: Dict[str, Any]) -> Dict[str, Any]:
    """Reduce a Phase-10B statement dict to the Client-Balance roster summary.

    Reuses ``aggregate_statement`` output verbatim — NO new payment logic is
    introduced here. Overdue is the invoice-age aged figure (aging total minus
    the ``current`` bucket); due-date overdue is NOT computed (architecture §7).
    """
    totals = stmt.get("totals_per_currency", {}) or {}
    aging  = stmt.get("aging_per_currency", {}) or {}
    ccys   = sorted(totals.keys())

    open_by_ccy     = {c: totals[c].get("outstanding", "0.00") for c in ccys}
    invoiced_by_ccy = {c: totals[c].get("invoiced", "0.00") for c in ccys}

    aged_by_ccy: Dict[str, str] = {}
    for c in ccys:
        a = aging.get(c, {}) or {}
        try:
            aged = Decimal(str(a.get("total", "0"))) - Decimal(str(a.get("current", "0")))
        except Exception:
            aged = Decimal("0")
        aged_by_ccy[c] = f"{aged:.2f}"

    open_total = _sum_ccy(open_by_ccy)
    single = ccys[0] if len(ccys) == 1 else None
    if single:
        currency = single
    elif len(ccys) > 1:
        currency = "multi"
    else:
        currency = default_currency or "—"

    return {
        "balance_available":               True,
        "currencies":                      ccys,
        "currency":                        currency,
        "open":                            (open_by_ccy[single] if single else None),
        "open_by_currency":                open_by_ccy,
        # Invoice-age basis ONLY — due-date overdue is Backend Pending.
        "overdue_invoice_age":             (aged_by_ccy[single] if single else None),
        "overdue_invoice_age_by_currency": aged_by_ccy,
        "overdue_due_date":                None,   # Backend Pending (PHASE10A.5)
        # YTD = invoiced within the (default year-to-date) statement window.
        "ytd_invoiced":                    (invoiced_by_ccy[single] if single else None),
        "ytd_invoiced_by_currency":        invoiced_by_ccy,
        "last_30d":                        None,   # Backend Pending
        "state":                           ("outstanding" if open_total > 0 else "clear"),
    }


def _unavailable_row(base: Dict[str, Any], default_currency: str,
                     note: str) -> Dict[str, Any]:
    """Honest placeholder row when a client has no balance (no contractor id,
    or the live wFirma read failed). No fabricated figures."""
    return {
        **base,
        "balance_available":   False,
        "currency":            default_currency or "—",
        "open":                None,
        "overdue_invoice_age": None,
        "overdue_due_date":    None,
        "ytd_invoiced":        None,
        "last_30d":            None,
        "state":               "unknown",
        "note":                note,
    }


@router.get("/clients", dependencies=[_auth])
def list_client_balances(
    from_:   str = Query("", alias="from",
                          description="Window start YYYY-MM-DD; default = current UTC quarter start"),
    to:      str = Query("", description="Window end YYYY-MM-DD; default = today UTC"),
    start:   int = Query(0, ge=0),
    limit:   int = Query(15, ge=1, le=100),
    country: str = Query("", description="Filter by ISO-3166 alpha-2 country"),
    q:       str = Query("", description="Case-insensitive name substring"),
    contractor: str = Query("", description="Exact wFirma contractor id"),
    currency: str = Query("", description="Filter by currency code (PLN/EUR/USD/…)"),
    status: str = Query("", description="Filter by state: outstanding|clear|unknown"),
    refresh: int = Query(0, ge=0, le=1, description="1 = bypass short-TTL AR fact cache"),
) -> JSONResponse:
    """Read-only Client Balance roster (Wave 4 Item 4).

    Client identity is owned by the **Customer Master**; balance / invoice /
    payment figures are owned by the existing **Statement authority**
    (``aggregate_statement_from_facts`` / shared AR remaining). One bulk
    invoices+payments load for the window — ``per_customer_wfirma_calls=0``.

    Outcomes:
      200 — roster JSON (rows may be empty)
      400 — invalid date / ``from > to``
      502 — bulk wFirma read failed
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    df = (from_ or "").strip() or _utc_quarter_start(today)
    dt = (to or "").strip() or today
    df = _validate_date("from", df)
    dt = _validate_date("to", dt)
    if df > dt:
        raise HTTPException(status_code=400, detail=f"from {df!r} is after to {dt!r}")

    contractor_f = (contractor or "").strip()
    currency_f = (currency or "").strip().upper()
    status_f = (status or "").strip().lower()

    customers = _cm_list_customers(
        _CM_DB_PATH,
        country=(country.strip().upper() or None),
        q=(q.strip() or None),
        active=True,
        limit=start + limit if not contractor_f else 5000,
    )
    if contractor_f:
        customers = [
            c for c in customers
            if (getattr(c, "bill_to_contractor_id", "") or "").strip() == contractor_f
        ]
    page = customers[start:start + limit]

    from ..services.ledger_fact_universe import (
        load_ar_fact_universe,
        timing_fields_from_universe,
    )
    from ..services.ledger_aggregator import build_statement_index_by_contractor

    try:
        t_route0 = time.perf_counter()
        uni = load_ar_fact_universe(df, dt, force=bool(refresh))
        t_agg0 = time.perf_counter()
        stmt_by_cid = build_statement_index_by_contractor(
            uni["invoice_facts"],
            uni["payment_facts"],
            statement_date=dt,
            period=(df, dt),
        )
        ej_aggregate_ms = int((time.perf_counter() - t_agg0) * 1000)
    except Exception as exc:
        log.warning("[client-balances] bulk AR read failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail={
                "error": f"wFirma bulk AR read failed: {exc}",
                "code": "CLIENT_BALANCES_BULK_FETCH_FAILED",
            },
        ) from exc

    empty_stmt = {
        "totals_per_currency": {},
        "aging_per_currency": {},
    }

    rows = []
    for cust in page:
        cid = (getattr(cust, "bill_to_contractor_id", "") or "").strip()
        base = {
            "contractor_id": cid,
            "name":          getattr(cust, "bill_to_name", "") or "",
            "country":       getattr(cust, "country", "") or "",
            "vat_id":        getattr(cust, "nip", "") or "",
        }
        default_ccy = getattr(cust, "default_currency", "") or ""
        if not cid:
            rows.append(_unavailable_row(base, default_ccy, "no wFirma contractor id"))
            continue
        stmt = stmt_by_cid.get(cid) or empty_stmt
        rows.append({**base, **_roster_row_from_statement(default_ccy, stmt)})

    if currency_f:
        rows = [
            r for r in rows
            if (r.get("currency") or "").upper() == currency_f
            or (
                r.get("currency") == "multi"
                and currency_f in (r.get("open_by_currency") or {})
            )
        ]
    if status_f:
        rows = [r for r in rows if (r.get("state") or "").lower() == status_f]

    inv_stats = uni.get("inv_stats") or {}
    pay_stats = uni.get("pay_stats") or {}
    qs = {
        "invoice_api_calls": int(inv_stats.get("api_calls") or 0),
        "payment_api_calls": int(pay_stats.get("api_calls") or 0),
        "invoices_normalized": len(uni.get("invoice_facts") or []),
        "payments_normalized": len(uni.get("payment_facts") or []),
        "per_customer_wfirma_calls": 0,
        "cache_hit": bool(uni.get("cache_hit")),
        "coalesced": bool(uni.get("coalesced")),
        "refresh": bool(refresh),
    }
    qs.update(timing_fields_from_universe(uni))
    qs["ej_aggregate_ms"] = ej_aggregate_ms
    qs["ej_ms"] = int(qs.get("ej_normalize_ms") or 0) + ej_aggregate_ms
    qs["route_wall_ms"] = int((time.perf_counter() - t_route0) * 1000)
    return JSONResponse({
        "period":       {"from": df, "to": dt},
        "start":        start,
        "limit":        limit,
        "count":        len(rows),
        "rows":         rows,
        "filters": {
            "contractor": contractor_f or None,
            "currency": currency_f or None,
            "status": status_f or None,
            "country": (country or "").strip().upper() or None,
            "q": (q or "").strip() or None,
        },
        "query_stats": qs,
        "column_status": {
            "open":                 "documented",
            "currency":             "documented",
            "state":                "documented",
            "ytd_invoiced":         "documented (invoiced in period)",
            "overdue_invoice_age":  "documented (invoice-age basis)",
            "overdue_due_date":     "backend_pending (PHASE10A.5 probe)",
            "last_30d":             "backend_pending",
        },
    })


def _build_management_analysis_dict(
    from_: str,
    to: str,
    as_of: str,
    currency: str,
    contractor_id: str,
    status: str,
    refresh: int,
    scope: str = "",
) -> Dict[str, Any]:
    """Validate → resolve window → build the receivables portfolio dict.

    The single AR analysis authority: ``management-analysis.json`` and
    ``management-analysis.pdf`` both call this, so the PDF is a projection of
    the same numbers the screen renders, not a second calculation.
    """
    df, dt, ao, sc = _resolve_analysis_window(scope, from_, to, as_of)

    ccy = (currency or "").strip().upper()
    if ccy and ccy not in ("USD", "EUR", "PLN"):
        raise HTTPException(
            status_code=400,
            detail="currency must be USD, EUR, PLN, or empty",
        )
    st = (status or "").strip().lower()
    if st and st not in ("outstanding", "overdue", "credit"):
        raise HTTPException(
            status_code=400,
            detail="status must be outstanding, overdue, credit, or empty",
        )

    from ..services.accounting_analytics import build_management_analysis

    try:
        body = build_management_analysis(
            date_from=df,
            date_to=dt,
            as_of=ao,
            currency=ccy,
            contractor_id=(contractor_id or "").strip(),
            status=st,
            force_refresh=bool(refresh),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        log.warning("[management-analysis] bulk read failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail={
                "error": f"wFirma portfolio read failed: {exc}",
                "code": "MANAGEMENT_ANALYSIS_FETCH_FAILED",
            },
        ) from exc

    # Echo the resolved scope so the all-outstanding lookback boundary is
    # visible on screen and in the PDF instead of being silent.
    filters = body.setdefault("filters", {})
    filters["scope"] = sc
    filters["outstanding_floor"] = df if sc == "all_outstanding" else None
    return body


@router.get(
    "/management-analysis.json",
    dependencies=[_auth],
)
def get_management_analysis(
    from_: str = Query("", alias="from", description="Window start YYYY-MM-DD"),
    to: str = Query("", description="Window end YYYY-MM-DD"),
    as_of: str = Query("", description="Aging anchor YYYY-MM-DD; default today UTC"),
    currency: str = Query("", description="Optional ISO filter: USD|EUR|PLN"),
    contractor_id: str = Query("", description="Optional single contractor filter"),
    status: str = Query(
        "",
        description="Optional: outstanding | overdue | credit",
    ),
    scope: str = Query(
        "",
        description="all_outstanding (from defaults to the configured floor, "
                    "to defaults to as_of) | custom_period | empty (= custom_period)",
    ),
    refresh: int = Query(0, ge=0, le=1, description="1 = bypass short-TTL AR fact cache"),
) -> JSONResponse:
    """Read-only receivables portfolio + due-date aging (Management Analysis).

    Bulk ``invoices/find`` + ``payments/find`` only — zero per-customer
    wFirma calls. Currency portfolios stay separate (no FX grand total).
    Drill-down remains ``/clients/{id}/statement.json``.
    """
    return JSONResponse(_build_management_analysis_dict(
        from_, to, as_of, currency, contractor_id, status, refresh, scope,
    ))


def _build_payables_analysis_dict(
    from_: str,
    to: str,
    as_of: str,
    currency: str,
    contractor_id: str,
    status: str,
    aging_bucket: str,
    refresh: int,
    scope: str = "",
) -> Dict[str, Any]:
    """Validate → resolve window → build the payables portfolio dict.

    The single AP analysis authority, shared by ``payables-analysis.json`` and
    the Management Analysis PDF.
    """
    df, dt, ao, sc = _resolve_analysis_window(scope, from_, to, as_of)

    ccy = (currency or "").strip().upper()
    if ccy and ccy not in ("USD", "EUR", "PLN", "CHF"):
        raise HTTPException(
            status_code=400,
            detail="currency must be USD, EUR, PLN, CHF, or empty",
        )
    st = (status or "").strip().lower()
    if st and st not in ("outstanding", "overdue", "credit"):
        raise HTTPException(
            status_code=400,
            detail="status must be outstanding, overdue, credit, or empty",
        )
    bucket = (aging_bucket or "").strip()
    allowed_buckets = {
        "not_due", "b_1_30", "b_31_90", "b_91_180", "b_180_plus",
        "due_date_unavailable",
    }
    if bucket and bucket not in allowed_buckets:
        raise HTTPException(
            status_code=400,
            detail=f"aging_bucket must be one of {sorted(allowed_buckets)} or empty",
        )

    from ..services.accounting_analytics import build_payables_analysis

    try:
        body = build_payables_analysis(
            date_from=df,
            date_to=dt,
            as_of=ao,
            currency=ccy,
            contractor_id=(contractor_id or "").strip(),
            status=st,
            aging_bucket=bucket,
            force_refresh=bool(refresh),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        log.warning("[payables-analysis] bulk read failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail={
                "error": f"wFirma payables read failed: {exc}",
                "code": "PAYABLES_ANALYSIS_FETCH_FAILED",
            },
        ) from exc

    filters = body.setdefault("filters", {})
    filters["scope"] = sc
    filters["outstanding_floor"] = df if sc == "all_outstanding" else None
    return body


@router.get(
    "/payables-analysis.json",
    dependencies=[_auth],
)
def get_payables_analysis(
    from_: str = Query("", alias="from", description="Window start YYYY-MM-DD"),
    to: str = Query("", description="Window end YYYY-MM-DD"),
    as_of: str = Query("", description="Aging anchor YYYY-MM-DD; default today UTC"),
    currency: str = Query("", description="Optional ISO filter: USD|EUR|PLN|CHF"),
    contractor_id: str = Query("", description="Optional single contractor filter"),
    status: str = Query(
        "",
        description="Optional: outstanding | overdue | credit",
    ),
    aging_bucket: str = Query(
        "",
        description="Optional bucket: not_due|b_1_30|b_31_90|b_91_180|b_180_plus|due_date_unavailable",
    ),
    scope: str = Query(
        "",
        description="all_outstanding (from defaults to the configured floor, "
                    "to defaults to as_of) | custom_period | empty (= custom_period)",
    ),
    refresh: int = Query(0, ge=0, le=1, description="1 = bypass short-TTL AP fact cache"),
) -> JSONResponse:
    """Read-only payables portfolio + creditor aging (Management Analysis).

    Bulk ``expenses/find`` + ``payments/find`` only — zero per-supplier
    wFirma calls. Currency portfolios stay separate (no FX grand total).
    Drill-down: ``/suppliers/{id}/statement.json``.
    """
    return JSONResponse(_build_payables_analysis_dict(
        from_, to, as_of, currency, contractor_id, status, aging_bucket,
        refresh, scope,
    ))


def _build_supplier_statement_dict(
    contractor_id: str,
    from_: str,
    to: str,
    as_of: str,
    refresh: int = 0,
    currency: str = "",
) -> Dict[str, Any]:
    """Validate → load shared AP facts → aggregate one supplier statement.

    The single Supplier Ledger authority: ``suppliers/{id}/statement.json``
    and ``suppliers/{id}/statement.pdf`` both call this, so the PDF cannot
    print a total the screen does not show.

    Optional ``currency`` keeps the selected AP financial row
    ``(contractor_id, currency)`` from returning sibling-currency sections.
    """
    cid = (contractor_id or "").strip()
    if not cid:
        raise HTTPException(status_code=400, detail="contractor_id is required")
    df = _validate_date("from", from_)
    dt = _validate_date("to", to)
    if df > dt:
        raise HTTPException(
            status_code=400,
            detail=f"from {df!r} is after to {dt!r}",
        )
    if (as_of or "").strip():
        ao = _validate_date("as_of", as_of)
    else:
        from datetime import datetime, timezone
        ao = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    ccy = (currency or "").strip().upper()
    if ccy and ccy not in ("USD", "EUR", "PLN", "CHF"):
        raise HTTPException(
            status_code=400,
            detail="currency must be USD, EUR, PLN, CHF, or empty",
        )

    try:
        from ..services.ledger_fact_universe import (
            load_ap_fact_universe,
            timing_fields_from_universe,
        )

        uni = load_ap_fact_universe(df, dt, force=bool(refresh))
        exp_stats = uni.get("exp_stats") or {}
        pay_stats = uni.get("pay_stats") or {}

        expense_facts = []
        supplier_name = ""
        for fact in uni.get("expense_facts") or []:
            if fact.get("contractor_id") != cid:
                continue
            if ccy and (fact.get("currency") or "") != ccy:
                continue
            if not supplier_name and fact.get("contractor_name"):
                supplier_name = fact["contractor_name"]
            expense_facts.append(fact)

        expense_ids = {f["id"] for f in expense_facts if f.get("id")}
        payment_facts = []
        for fact in uni.get("payment_facts") or []:
            linked = fact.get("linked_expense") or ""
            if fact.get("contractor_id") == cid or (linked and linked in expense_ids):
                if ccy:
                    # Keep matched payments for the selected currency only —
                    # unmatched / other-ccy noise must not leak into USD vs EUR.
                    pay_ccy = (fact.get("currency") or "")
                    if linked and linked in expense_ids:
                        pass  # inherit via aggregator from the filtered expense
                    elif pay_ccy and pay_ccy != ccy:
                        continue
                payment_facts.append(fact)

        body = aggregate_supplier_statement(
            expense_facts,
            payment_facts,
            contractor_meta=_supplier_meta_from_master(cid, supplier_name),
            period=(df, dt),
            as_of=ao,
        )
        if ccy:
            body = _restrict_supplier_statement_currency(body, ccy)
        qs = {
            "expense_api_calls": int(exp_stats.get("api_calls") or 0),
            "payment_api_calls": int(pay_stats.get("api_calls") or 0),
            "expenses_in_scope": len(expense_facts),
            "payments_in_scope": len(payment_facts),
            "per_supplier_wfirma_calls": 0,
            "cache_hit": bool(uni.get("cache_hit")),
            "coalesced": bool(uni.get("coalesced")),
            "note": "shared AP fact universe + Python contractor filter",
        }
        qs.update(timing_fields_from_universe(uni))
        body["query_stats"] = qs
    except HTTPException:
        raise
    except Exception as exc:
        log.warning("[supplier-statement] read failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail={
                "error": f"wFirma supplier statement failed: {exc}",
                "code": "SUPPLIER_STATEMENT_FETCH_FAILED",
            },
        ) from exc

    return body


def _restrict_supplier_statement_currency(
    body: Dict[str, Any], currency: str,
) -> Dict[str, Any]:
    """Keep only one currency section — no FX merge, no sibling leakage."""
    ccy = (currency or "").strip().upper()
    if not ccy:
        return body
    out = dict(body)
    out["currencies"] = [c for c in (body.get("currencies") or []) if c == ccy]
    for key in (
        "entries_per_currency",
        "totals_per_currency",
        "aging_per_currency",
        "unmatched_payments_per_currency",
    ):
        mapping = body.get(key) or {}
        if isinstance(mapping, dict) and ccy in mapping:
            out[key] = {ccy: mapping[ccy]}
        elif isinstance(mapping, dict):
            out[key] = {}
    return out


@router.get(
    "/suppliers/{contractor_id}/statement.json",
    dependencies=[_auth],
)
def get_supplier_statement(
    contractor_id: str,
    from_: str = Query("", alias="from", description="Window start YYYY-MM-DD"),
    to: str = Query("", description="Window end YYYY-MM-DD"),
    as_of: str = Query("", description="As-of date YYYY-MM-DD"),
    currency: str = Query("", description="Optional ISO filter: USD|EUR|PLN|CHF"),
    refresh: int = Query(0, ge=0, le=1, description="1 = bypass short-TTL AP fact cache"),
) -> JSONResponse:
    """Read-only Supplier Ledger drill-down from shared AP facts.

    Reuses the shared AP fact universe (same bulk expenses+payments as
    payables-analysis), then Python-side contractor filter. Same remaining
    equation as Payables portfolio — no second authority.
    """
    return JSONResponse(
        _build_supplier_statement_dict(
            contractor_id, from_, to, as_of, refresh, currency,
        )
    )


@router.get(
    "/suppliers/{contractor_id}/statement.pdf",
    dependencies=[_auth],
)
def get_supplier_statement_pdf(
    contractor_id: str,
    from_: str = Query("", alias="from", description="Window start YYYY-MM-DD"),
    to: str = Query("", description="Window end YYYY-MM-DD"),
    as_of: str = Query("", description="As-of date YYYY-MM-DD"),
    currency: str = Query("", description="Optional ISO filter: USD|EUR|PLN|CHF"),
    refresh: int = Query(0, ge=0, le=1, description="1 = bypass short-TTL AP fact cache"),
) -> Response:
    """Read-only PDF rendering of the Supplier Ledger statement.

    Identical contract to ``/suppliers/{id}/statement.json``: same validation,
    same shared AP fact universe, same aggregation. The PDF is rendered from
    the resulting dict — no second arithmetic path.

    Business-facing presentation: reuses the Company Profile seller footer and
    document logo; omits wFirma ids, raw metadata and DQ warnings.
    """
    statement = _build_supplier_statement_dict(
        contractor_id, from_, to, as_of, refresh, currency,
    )

    try:
        pdf_bytes = render_supplier_statement_pdf(
            statement,
            seller=_statement_seller_block(),
            logo_path=_statement_logo_path(),
        )
    except Exception as exc:
        log.warning(
            "[supplier-statement-pdf %s] render failed: %s", contractor_id, exc,
        )
        raise HTTPException(
            status_code=502,
            detail={
                "error": f"PDF render failed: {exc}",
                "code": "SUPPLIER_STATEMENT_PDF_RENDER_FAILED",
                "wfirma_contractor_id": (contractor_id or "").strip(),
            },
        ) from exc

    filename = (
        f"supplier-statement-{_safe_filename(contractor_id)}"
        f"{('-' + currency.strip().upper()) if (currency or '').strip() else ''}"
        f"-{from_}-{to}.pdf"
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@router.get(
    "/management-analysis.pdf",
    dependencies=[_auth],
)
def get_management_analysis_pdf(
    from_: str = Query("", alias="from", description="Window start YYYY-MM-DD"),
    to: str = Query("", description="Window end YYYY-MM-DD"),
    as_of: str = Query("", description="Aging anchor YYYY-MM-DD; default today UTC"),
    currency: str = Query("", description="Optional ISO filter"),
    contractor_id: str = Query("", description="Optional single contractor filter"),
    status: str = Query("", description="AR status: outstanding | overdue | credit"),
    ap_status: str = Query("", description="AP status: outstanding | overdue | credit"),
    aging_bucket: str = Query("", description="Optional AP bucket filter"),
    scope: str = Query("", description="all_outstanding | custom_period | empty"),
    refresh: int = Query(0, ge=0, le=1, description="1 = bypass short-TTL fact caches"),
) -> Response:
    """Read-only PDF rendering of Management Analysis (AR + AP).

    Takes the same parameter set as the two JSON routes and calls the same
    builders, so every figure in the report is the figure on screen. AR and AP
    status travel separately because one report renders both portfolios.
    Currencies are reported in separate sections — there is no cross-currency
    grand total anywhere in the document.
    """
    ar = _build_management_analysis_dict(
        from_, to, as_of, currency, contractor_id, status, refresh, scope,
    )
    ap = _build_payables_analysis_dict(
        from_, to, as_of, currency, contractor_id, ap_status, aging_bucket,
        refresh, scope,
    )

    try:
        pdf_bytes = render_management_analysis_pdf(
            ar, ap,
            seller=_statement_seller_block(),
            logo_path=_statement_logo_path(),
        )
    except Exception as exc:
        log.warning("[management-analysis-pdf] render failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail={
                "error": f"PDF render failed: {exc}",
                "code": "MANAGEMENT_ANALYSIS_PDF_RENDER_FAILED",
            },
        ) from exc

    period = ar.get("period") or {}
    filename = (
        "management-analysis-"
        f"{_safe_filename(str(period.get('from') or ''))}-"
        f"{_safe_filename(str(period.get('to') or ''))}.pdf"
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )