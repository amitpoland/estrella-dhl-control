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
        nodes = wfirma_client.fetch_invoices_for_contractor(
            cid, df, dt,
            types=("normal", "correction", "proforma"),
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
# invoice-age aging buckets. Architecture pinned by
# ``docs/PHASE10B_STATEMENT_ARCHITECTURE.md``.
#
# Aging method is HARDCODED to ``invoice_age``. Switching to
# ``due_date`` requires the Phase 10A.5 follow-up probe (real invoice
# id) to confirm <paymentdate> presence on invoices/get responses —
# until that lands, due-date aging is forbidden (architecture doc §7).


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


def _build_statement_dict(
    contractor_id: str,
    from_:         str,
    to:            str,
    as_of:         str,
) -> Dict[str, Any]:
    """Shared builder used by BOTH ``/statement.json`` and
    ``/statement.pdf`` routes. Performs every validation, preflight,
    fetch, Python-side filter, and aggregation step. Returns the
    Phase 10B aggregate_statement output dict.

    Raises ``HTTPException`` (400 / 404 / 502) on any failure. The PDF
    route inherits the same error shapes without duplication.

    Pure side-effects on wFirma: none. Read-only by construction.
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

    contractor_meta = {
        "wfirma_contractor_id": cid,
        "name":     getattr(rcv, "name",    "") or "",
        "country":  getattr(rcv, "country", "") or "",
        "vat_id":   getattr(rcv, "nip",     "") or "",
    }

    # Fetch invoices.
    try:
        invoice_nodes = wfirma_client.fetch_invoices_for_contractor(
            cid, df, dt,
            types=("normal", "correction", "proforma"),
        )
    except Exception as exc:
        log.warning(
            "[statement %s] fetch_invoices_for_contractor failed: %s",
            cid, exc,
        )
        raise HTTPException(
            status_code=502,
            detail={
                "error": f"wFirma invoices/find failed: {exc}",
                "code":  "STATEMENT_INVOICE_FETCH_FAILED",
                "wfirma_contractor_id": cid,
            },
        )

    # Fetch payments.
    try:
        payment_nodes = wfirma_client.fetch_payments_for_contractor(
            cid, df, dt,
        )
    except Exception as exc:
        log.warning(
            "[statement %s] fetch_payments_for_contractor failed: %s",
            cid, exc,
        )
        raise HTTPException(
            status_code=502,
            detail={
                "error": f"wFirma payments/find failed: {exc}",
                "code":  "STATEMENT_PAYMENT_FETCH_FAILED",
                "wfirma_contractor_id": cid,
            },
        )

    # Defence-in-depth Python-side date filtering.
    # Period statement model: issue-date window for invoices and payment-date
    # window for payments independently. Outside-window invoice links stay
    # flagged — the window is not silently broadened (no opening-balance mix).
    invoice_nodes = _python_side_date_filter(invoice_nodes, df, dt)
    payment_nodes = _python_side_payment_date_filter(payment_nodes, df, dt)

    return aggregate_statement(
        contractor_meta = contractor_meta,
        invoice_nodes   = invoice_nodes,
        payment_nodes   = payment_nodes,
        statement_date  = ao,
        period          = (df, dt),
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
) -> JSONResponse:
    """Read-only Statement of Account for one wFirma contractor.

    Combines ``invoices/find`` + ``payments/find`` and emits a
    per-currency Statement with entries (invoice / correction /
    proforma / payment), running balance, totals (invoiced / credited /
    received / outstanding), aging (invoice_age method), unmatched
    payments, and operator-actionable warnings.

    Outcomes:
      200  — JSON Statement (empty per-currency maps when no activity)
      400  — invalid contractor id, invalid date, ``from > to``,
              ``as_of < from``
      404  — contractor not found in wFirma
      502  — wFirma fetch failed (HTTP / parse / non-OK status) on
              invoices/find OR payments/find.
    """
    body = _build_statement_dict(contractor_id, from_, to, as_of)
    return JSONResponse(body)


# ── Phase 10C — Statement PDF ──────────────────────────────────────────────
#
# Pure renderer over the Phase 10B JSON model. The route reuses
# ``_build_statement_dict`` for validation + fetch + aggregation, then
# hands the dict to ``render_statement_pdf`` (which performs no I/O,
# no DB read, no wFirma round-trip).

from fastapi import Response   # noqa: E402  — kept here, route-local
from ..services.statement_pdf_renderer import render_statement_pdf  # noqa: E402


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
) -> Response:
    """Read-only PDF rendering of the Statement of Account.

    Identical contract to ``/statement.json``: same validation, same
    preflight, same fetch, same aggregation. The PDF is rendered from
    the resulting dict — no second wFirma round-trip.

    Outcomes:
      200  — application/pdf, ``Content-Disposition: inline``
      400  — same shapes as the JSON route
      404  — same
      502  — STATEMENT_PDF_PREFLIGHT_FAILED |
              STATEMENT_PDF_INVOICE_FETCH_FAILED |
              STATEMENT_PDF_PAYMENT_FETCH_FAILED |
              STATEMENT_PDF_RENDER_FAILED
    """
    statement = _build_statement_dict(contractor_id, from_, to, as_of)

    try:
        pdf_bytes = render_statement_pdf(statement)
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
        },
    )


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
    refresh: int = Query(0, ge=0, le=1, description="1 = bypass short-TTL AR fact cache"),
) -> JSONResponse:
    """Read-only receivables portfolio + due-date aging (Management Analysis).

    Bulk ``invoices/find`` + ``payments/find`` only — zero per-customer
    wFirma calls. Currency portfolios stay separate (no FX grand total).
    Drill-down remains ``/clients/{id}/statement.json``.
    """
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

    return JSONResponse(body)


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
    refresh: int = Query(0, ge=0, le=1, description="1 = bypass short-TTL AP fact cache"),
) -> JSONResponse:
    """Read-only payables portfolio + creditor aging (Management Analysis).

    Bulk ``expenses/find`` + ``payments/find`` only — zero per-supplier
    wFirma calls. Currency portfolios stay separate (no FX grand total).
    Drill-down: ``/suppliers/{id}/statement.json``.
    """
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

    return JSONResponse(body)


@router.get(
    "/suppliers/{contractor_id}/statement.json",
    dependencies=[_auth],
)
def get_supplier_statement(
    contractor_id: str,
    from_: str = Query("", alias="from", description="Window start YYYY-MM-DD"),
    to: str = Query("", description="Window end YYYY-MM-DD"),
    as_of: str = Query("", description="As-of date YYYY-MM-DD"),
    refresh: int = Query(0, ge=0, le=1, description="1 = bypass short-TTL AP fact cache"),
) -> JSONResponse:
    """Read-only Supplier Ledger drill-down from shared AP facts.

    Reuses the shared AP fact universe (same bulk expenses+payments as
    payables-analysis), then Python-side contractor filter. Same remaining
    equation as Payables portfolio — no second authority.
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
            if not supplier_name and fact.get("contractor_name"):
                supplier_name = fact["contractor_name"]
            expense_facts.append(fact)

        expense_ids = {f["id"] for f in expense_facts if f.get("id")}
        payment_facts = []
        for fact in uni.get("payment_facts") or []:
            linked = fact.get("linked_expense") or ""
            if fact.get("contractor_id") == cid or (linked and linked in expense_ids):
                payment_facts.append(fact)

        body = aggregate_supplier_statement(
            expense_facts,
            payment_facts,
            contractor_meta={
                "wfirma_contractor_id": cid,
                "name": supplier_name or cid,
            },
            period=(df, dt),
            as_of=ao,
        )
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
    except Exception as exc:
        log.warning("[supplier-statement] read failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail={
                "error": f"wFirma supplier statement failed: {exc}",
                "code": "SUPPLIER_STATEMENT_FETCH_FAILED",
            },
        ) from exc

    return JSONResponse(body)