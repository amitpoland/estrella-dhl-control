"""
accounting_analytics.py — Phase 1 Management Analysis portfolio projection.
==========================================================================

Read-only receivables / debtor-aging projection over the SAME invoice and
payment facts consumed by Client Ledger (ledger_aggregator).

No wFirma writes. No second ledger DB. No FX consolidation across
USD/EUR/PLN. Aging uses invoice ``paymentdate`` (due date), never issue
date, for positive remainings.

Period semantics (identical to Client Ledger / fact-universe loader):
  • invoices / expenses — ACTIVITY: issue date in [from, to]
  • payments — POSITION settlements: payment_date <= as_of upper (date_to);
    not dropped merely because payment_date < from
  • remaining_after_payments / match_payments_* remain the money authority
"""
from __future__ import annotations

import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .financial_aging import (
    AGING_BUCKETS_WITH_UNAVAILABLE,
    due_bucket,
    empty_buckets,
    overdue_total,
    sum_buckets as _sum_aging_buckets,
)
from .ledger_aggregator import (
    _days_between,
    _parse_expense_fact,
    _parse_invoice_fact,
    _parse_payment_fact,
    _q,
    match_payments_to_expenses,
    match_payments_to_invoices,
    remaining_after_payments,
)
from . import wfirma_client


# Re-export canonical keys for statement/supplier aging consumers that still
# import from this module (ledger_aggregator supplier statement path).
_BUCKETS = AGING_BUCKETS_WITH_UNAVAILABLE
_due_bucket = due_bucket


def _empty_buckets() -> Dict[str, Decimal]:
    return empty_buckets(include_unavailable=True)


def _sum_buckets(rows: List[Dict[str, Any]]) -> Dict[str, Decimal]:
    """Per-bucket totals for one currency's rows.

    The currency-level aging breakdown belongs to this layer, not to the screen
    or the PDF: both are projections of the summary this returns.
    """
    return _sum_aging_buckets(rows, include_unavailable=True)


def _python_filter_by_date(nodes, df: str, dt: str, date_tag: str = "date"):
    if not (df or dt):
        return list(nodes or [])
    out = []
    for n in nodes or []:
        d = (n.findtext(date_tag) or "").strip()
        if not d:
            out.append(n)
            continue
        if df and d < df:
            continue
        if dt and d > dt:
            continue
        out.append(n)
    return out


def build_portfolio_from_facts(
    invoice_facts: List[Dict[str, Any]],
    payment_facts: List[Dict[str, Any]],
    *,
    as_of: str,
    period: Tuple[str, str],
    currency_filter: str = "",
    contractor_filter: str = "",
    status_filter: str = "",
    query_stats: Optional[Dict[str, Any]] = None,
    source_health: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Pure portfolio projection from already-parsed facts.

    *status_filter*: ``""`` | ``outstanding`` | ``overdue`` | ``credit``.
    """
    df, dt = period if period else ("", "")
    ccy_f = (currency_filter or "").strip().upper()
    cid_f = (contractor_filter or "").strip()
    status_f = (status_filter or "").strip().lower()

    # Fiscal boundary — drop proforma before payment match so a payment
    # linked only to a proforma cannot settle fiscal AR.
    fiscal_invoices: List[Dict[str, Any]] = []
    pre_warnings: List[Dict[str, Any]] = []
    for inv in invoice_facts or []:
        if (inv.get("type") or "").strip() == "proforma":
            pre_warnings.append({
                "event": "proforma_excluded_from_fiscal",
                "wfirma_doc_id": inv.get("id") or "",
            })
            continue
        fiscal_invoices.append(inv)
    invoice_facts = fiscal_invoices

    match = match_payments_to_invoices(invoice_facts, payment_facts)
    paid_map: Dict[str, Decimal] = match["paid_against_invoice"]
    warnings = list(pre_warnings) + list(match["warnings"])

    data_quality: Dict[str, int] = defaultdict(int)
    for w in warnings:
        ev = w.get("event") or "other"
        data_quality[ev] += 1
    if pre_warnings:
        data_quality["proforma_excluded_from_fiscal"] += len(pre_warnings)

    # Per (contractor_id, currency) accumulators
    CustKey = Tuple[str, str]
    cust: Dict[CustKey, Dict[str, Any]] = {}

    def _row(key: CustKey, name: str) -> Dict[str, Any]:
        if key not in cust:
            cust[key] = {
                "contractor_id": key[0],
                "customer_name": name or "—",
                "currency": key[1],
                "buckets": _empty_buckets(),
                "credit_balance": Decimal("0"),
                "invoice_count": 0,
                "open_invoice_count": 0,
                "oldest_due_date": "",
                "days_oldest_overdue": 0,
                "last_invoice_date": "",
                "last_payment_date": "",
                "gross_invoiced": Decimal("0"),
                "credits_docs": Decimal("0"),
                "payments_applied": Decimal("0"),
                "receipts_last_30d": Decimal("0"),
            }
        elif name and cust[key]["customer_name"] in ("", "—"):
            cust[key]["customer_name"] = name
        return cust[key]

    invoices_with_due = 0
    invoices_missing_due = 0
    open_with_due = 0
    open_missing_due = 0

    for inv in invoice_facts:
        cid = inv.get("contractor_id") or ""
        ccy = inv.get("currency") or ""
        if not inv.get("id"):
            data_quality["invoice_with_empty_id"] += 1
            continue
        if not ccy:
            data_quality["invoice_currency_missing"] += 1
            data_quality["unsupported_currency"] += 1
            continue
        if ccy_f and ccy != ccy_f:
            continue
        if cid_f and cid != cid_f:
            continue

        gross = inv.get("brutto")
        if gross is None:
            data_quality["invalid_monetary_field"] += 1
            continue

        # Signed document contribution (credit notes → credits_docs).
        if inv.get("type") == "correction" and gross < 0:
            row = _row((cid, ccy), inv.get("contractor_name") or "")
            row["invoice_count"] += 1
            row["credits_docs"] += -gross
            # remaining still computed — typically negative until matched
        else:
            row = _row((cid, ccy), inv.get("contractor_name") or "")
            row["invoice_count"] += 1
            if gross > 0:
                row["gross_invoiced"] += gross

        paid = paid_map.get(inv["id"], Decimal("0"))
        rem = remaining_after_payments(gross, paid)
        row["payments_applied"] += paid

        idate = inv.get("date") or ""
        if idate and (not row["last_invoice_date"] or idate > row["last_invoice_date"]):
            row["last_invoice_date"] = idate

        due = inv.get("paymentdate") or ""
        if due:
            invoices_with_due += 1
        else:
            invoices_missing_due += 1

        if rem > 0:
            row["open_invoice_count"] += 1
            if due:
                open_with_due += 1
                days = _days_between(as_of, due)
                bucket = _due_bucket(days)
                row["buckets"][bucket] += rem
                if not row["oldest_due_date"] or due < row["oldest_due_date"]:
                    row["oldest_due_date"] = due
                if days > row["days_oldest_overdue"]:
                    row["days_oldest_overdue"] = days
            else:
                open_missing_due += 1
                data_quality["paymentdate_missing"] += 1
                row["buckets"]["due_date_unavailable"] += rem
        elif rem < 0:
            # Excess payment / credit note position — never into aging buckets.
            row["credit_balance"] += -rem

    # Last payment date + last-30d applied receipts from matched payments.
    # Window: 30 calendar dates ending as_of (inclusive). Not a second knock-off.
    try:
        receipts_from = (
            datetime.strptime(as_of[:10], "%Y-%m-%d") - timedelta(days=29)
        ).strftime("%Y-%m-%d")
    except ValueError:
        receipts_from = ""
    inv_by_id = {f["id"]: f for f in invoice_facts if f.get("id")}
    for p in payment_facts:
        if p["id"] not in match["matched_payment_ids"]:
            continue
        linked = p.get("linked_invoice") or ""
        inv = inv_by_id.get(linked)
        if not inv:
            continue
        ccy = inv.get("currency") or ""
        cid = inv.get("contractor_id") or ""
        if ccy_f and ccy != ccy_f:
            continue
        if cid_f and cid != cid_f:
            continue
        key = (cid, ccy)
        if key not in cust:
            continue
        pd = (p.get("date") or "")[:10]
        if pd and (not cust[key]["last_payment_date"] or pd > cust[key]["last_payment_date"]):
            cust[key]["last_payment_date"] = pd
        if pd and receipts_from and receipts_from <= pd <= as_of[:10]:
            val = p.get("value")
            if val is not None:
                cust[key]["receipts_last_30d"] += val

    # Build customer rows + apply status filter
    customers: List[Dict[str, Any]] = []
    for key, row in cust.items():
        buckets = row["buckets"]
        receivable = sum((buckets[b] for b in _BUCKETS), Decimal("0"))
        credit = row["credit_balance"]
        outstanding = receivable  # positive AR only; credits separate
        overdue = overdue_total(buckets)
        not_due = buckets["not_due"]

        if status_f == "outstanding" and outstanding <= 0 and credit <= 0:
            continue
        if status_f == "overdue" and overdue <= 0:
            continue
        if status_f == "credit" and credit <= 0:
            continue

        customers.append({
            "contractor_id": row["contractor_id"],
            "customer_name": row["customer_name"],
            "currency": row["currency"],
            "payment_terms": "due_date",  # basis = paymentdate
            "credit_balance": _q(credit),
            "not_due": _q(not_due),
            "b_1_30": _q(buckets["b_1_30"]),
            "b_31_60": _q(buckets["b_31_60"]),
            "b_61_90": _q(buckets["b_61_90"]),
            "b_91_180": _q(buckets["b_91_180"]),
            "b_181_365": _q(buckets["b_181_365"]),
            "b_365_plus": _q(buckets["b_365_plus"]),
            "due_date_unavailable": _q(buckets["due_date_unavailable"]),
            "outstanding": _q(outstanding),
            "overdue": _q(overdue),
            # Period gross invoices already accumulated — exposed for Client
            # Balance activity column (not a second formula).
            "gross_invoiced": _q(row["gross_invoiced"]),
            "receipts_last_30d": _q(row["receipts_last_30d"]),
            "oldest_due_date": row["oldest_due_date"] or None,
            "days_oldest_overdue": int(row["days_oldest_overdue"]),
            "last_invoice_date": row["last_invoice_date"] or None,
            "last_payment_date": row["last_payment_date"] or None,
            "invoice_count": int(row["invoice_count"]),
            "open_invoice_count": int(row["open_invoice_count"]),
            # ── Customer-level economic position, beside the gross truth ────
            # ``outstanding`` and every aging bucket stay GROSS: aging_basis is
            # gross_before_credits and audit needs the source figure intact.
            #
            # These two fields are customer-level facts already computed here,
            # published so the screen never recomputes them. DELIBERATELY NOT
            # published: any "net 365+". Netting a credit against the 365+
            # bucket asserts WHICH old document the credit offsets, and only
            # the canonical payment/correction linkage can prove that. Absent
            # that proof it would be an invented allocation, so the management
            # indicator must read "gross 365+ exposure, customer credit
            # available" and never imply a bucket-level allocation.
            #
            # Why this matters, measured 2026-08-20: 115,262.66 of the
            # 126,341.72 USD at 365+ sits on customers whose total credit
            # equals or exceeds their total outstanding — UAB Tomas Gold
            # 52,940 against a 52,940 credit. Their customer-level net is 0,
            # which IS provable without any allocation assumption.
            "net_position": _q(outstanding - credit),
            "offset_status": (
                "fully_offset" if credit >= outstanding and credit > 0
                else "partially_offset" if credit > 0
                else "actionable"
            ),
        })

    # Default sort: actionable positive net first, then partially offset, then
    # fully-offset / credit-only last, with a stable name tie-break.
    #
    # Was ``-overdue, -outstanding`` — both GROSS — so a customer whose balance
    # is wholly offset by credit notes outranked one who genuinely owes money.
    # net_position is a canonical customer-level economic position, so ranking
    # on it asserts nothing about which document a credit offsets. Sorting
    # happens HERE, before the route paginates, so page 1 is the largest real
    # exposure and never a formatted-string sort in the browser.
    _OFFSET_RANK = {"actionable": 0, "partially_offset": 1, "fully_offset": 2}
    customers.sort(
        key=lambda r: (
            _OFFSET_RANK.get(r["offset_status"], 0),
            -Decimal(r["net_position"]),
            -Decimal(r["overdue"]),
            r["customer_name"] or "",
            r["contractor_id"] or "",
        )
    )

    # Currency summaries — never cross-currency totals
    by_ccy: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in customers:
        by_ccy[r["currency"]].append(r)

    currency_summaries: List[Dict[str, Any]] = []
    for ccy in sorted(by_ccy.keys()):
        rows = by_ccy[ccy]
        recv = sum((Decimal(r["outstanding"]) for r in rows), Decimal("0"))
        ovd = sum((Decimal(r["overdue"]) for r in rows), Decimal("0"))
        nd = sum((Decimal(r["not_due"]) for r in rows), Decimal("0"))
        cr = sum((Decimal(r["credit_balance"]) for r in rows), Decimal("0"))
        buckets = _sum_buckets(rows)
        dua = buckets["due_date_unavailable"]
        # Invariant pieces
        aging_sum = sum(buckets.values(), Decimal("0"))
        oldest_days = max((int(r["days_oldest_overdue"]) for r in rows), default=0)
        currency_summaries.append({
            "currency": ccy,
            "total_receivable": _q(recv),
            "overdue": _q(ovd),
            "not_due": _q(nd),
            "customer_credits": _q(cr),
            "due_date_unavailable": _q(dua),
            "customers_outstanding": sum(
                1 for r in rows if Decimal(r["outstanding"]) > 0
            ),
            "customers_overdue": sum(
                1 for r in rows if Decimal(r["overdue"]) > 0
            ),
            "customers_with_credit": sum(
                1 for r in rows if Decimal(r["credit_balance"]) > 0
            ),
            "oldest_overdue_days": oldest_days,
            "invoices_represented": sum(int(r["invoice_count"]) for r in rows),
            "open_invoices": sum(int(r["open_invoice_count"]) for r in rows),
            "aging_plus_unavailable": _q(aging_sum),
            "aging": {b: _q(v) for b, v in buckets.items()},
            "reconciliation_ok": aging_sum == recv,
            "net_position": _q(recv - cr),
        })

    open_total = open_with_due + open_missing_due
    due_coverage_pct = (
        round(100.0 * open_with_due / open_total, 2) if open_total else None
    )

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "generated_at": generated_at,
        "as_of": as_of,
        "period": {"from": df, "to": dt},
        "filters": {
            "currency": ccy_f or None,
            "contractor_id": cid_f or None,
            "status": status_f or None,
        },
        "source_health": source_health or {"ok": True},
        "currency_summaries": currency_summaries,
        "customers": customers,
        "data_quality": dict(data_quality),
        "due_date_coverage": {
            "invoices_with_paymentdate": invoices_with_due,
            "invoices_missing_paymentdate": invoices_missing_due,
            "open_with_paymentdate": open_with_due,
            "open_missing_paymentdate": open_missing_due,
            "open_coverage_pct": due_coverage_pct,
        },
        "query_stats": query_stats or {},
        "warnings": warnings[:200],  # bound payload size
    }


class LocalProjectionUnavailable(RuntimeError):
    """Raised when source=local but the reporting projection is empty/missing."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def build_management_analysis(
    *,
    date_from: str,
    date_to: str,
    as_of: str = "",
    currency: str = "",
    contractor_id: str = "",
    status: str = "",
    types: tuple = (),
    force_refresh: bool = False,
    source: str = "local",
    storage_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Receivables portfolio for Management Analysis / CFO MIS.

    Default ``source=local`` reads the verified financial reporting projection
    (zero live wFirma waterfall). Use ``source=live`` or ``force_refresh=True``
    for controlled reconciliation / cache-bypass live reads.

    Default invoice types = fiscal AR (normal + correction). Proforma is
    never part of Management Analysis receivables.
    """
    df = (date_from or "").strip()
    dt = (date_to or "").strip()
    if not df or not dt:
        raise ValueError("date_from and date_to are required")
    if df > dt:
        raise ValueError(f"date_from {df!r} is after date_to {dt!r}")
    ao = (as_of or "").strip() or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    from .ledger_fact_universe import (
        FISCAL_AR_INVOICE_TYPES,
        load_ar_fact_universe,
        timing_fields_from_universe,
    )

    type_set = types if types else FISCAL_AR_INVOICE_TYPES
    src = (source or "local").strip().lower()
    if force_refresh:
        src = "live"
    if src not in ("local", "live"):
        raise ValueError("source must be local or live")

    provenance: Dict[str, Any] = {}
    if src == "local":
        from .local_fact_universe import (
            load_ar_fact_universe_local,
            local_projection_available,
        )
        from ..core.config import settings

        root = Path(storage_root) if storage_root else Path(settings.storage_root)
        ok, reason = local_projection_available(root)
        if not ok:
            raise LocalProjectionUnavailable(reason)
        uni = load_ar_fact_universe_local(root, df, dt, types=type_set)
        provenance = uni.get("provenance") or {}
    else:
        uni = load_ar_fact_universe(df, dt, types=type_set, force=force_refresh)
        provenance = {
            "source": "live",
            "freshness": "live",
            "reconciliation_status": "live_wfirma",
            "as_of_generated_at": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat(),
        }

    invoice_facts = uni["invoice_facts"]
    payment_facts = uni["payment_facts"]
    inv_stats = uni.get("inv_stats") or {}
    pay_stats = uni.get("pay_stats") or {}

    t_agg0 = time.perf_counter()
    query_stats = {
        "source": src,
        "invoice_api_calls": int(inv_stats.get("api_calls") or 0),
        "payment_api_calls": int(pay_stats.get("api_calls") or 0),
        "invoice_pages": int(inv_stats.get("pages") or 0),
        "payment_pages": int(pay_stats.get("pages") or 0),
        "invoices_normalized": len(invoice_facts),
        "payments_normalized": len(payment_facts),
        "invoice_duplicates_suppressed": int(
            inv_stats.get("duplicate_ids_suppressed") or 0
        ),
        "payment_duplicates_suppressed": int(
            pay_stats.get("duplicate_ids_suppressed") or 0
        ),
        "invoice_stop_reason": inv_stats.get("stopped_reason"),
        "payment_stop_reason": pay_stats.get("stopped_reason"),
        "per_customer_wfirma_calls": 0,
        "cache_hit": bool(uni.get("cache_hit")),
        "coalesced": bool(uni.get("coalesced")),
    }
    query_stats.update(timing_fields_from_universe(uni))
    health = {
        "ok": True,
        "source": src,
        "invoice_cap_hit": inv_stats.get("stopped_reason") == "safety_cap",
        "payment_cap_hit": pay_stats.get("stopped_reason") == "safety_cap",
        "invoice_paging_stalled": inv_stats.get("stopped_reason") == "no_new_ids",
        "payment_paging_stalled": pay_stats.get("stopped_reason") == "no_new_ids",
    }
    if health["invoice_cap_hit"] or health["payment_cap_hit"]:
        health["ok"] = False
        health["note"] = "Safety cap hit — portfolio may be incomplete"
    if src == "local" and provenance.get("freshness") == "stale":
        health["ok"] = True
        health["note"] = "Local projection is stale — refresh for live reconciliation"

    portfolio = build_portfolio_from_facts(
        invoice_facts,
        payment_facts,
        as_of=ao,
        period=(df, dt),
        currency_filter=currency,
        contractor_filter=contractor_id,
        status_filter=status,
        query_stats=query_stats,
        source_health=health,
    )
    ej_aggregate_ms = int((time.perf_counter() - t_agg0) * 1000)
    qs = portfolio.get("query_stats") or query_stats
    qs["ej_aggregate_ms"] = ej_aggregate_ms
    qs["ej_ms"] = int(qs.get("ej_normalize_ms") or 0) + ej_aggregate_ms
    portfolio["query_stats"] = qs
    portfolio["source"] = provenance.get("source") or src
    portfolio["freshness"] = provenance.get("freshness") or src
    portfolio["reconciliation_status"] = provenance.get("reconciliation_status")
    portfolio["projection"] = provenance.get("projection")
    return portfolio


def build_payables_portfolio_from_facts(
    expense_facts: List[Dict[str, Any]],
    payment_facts: List[Dict[str, Any]],
    *,
    as_of: str,
    period: Tuple[str, str],
    currency_filter: str = "",
    contractor_filter: str = "",
    status_filter: str = "",
    aging_bucket_filter: str = "",
    query_stats: Optional[Dict[str, Any]] = None,
    source_health: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Pure Supplier AP / creditor-aging projection from ExpenseFact + PaymentFact.

    Sign convention (explicit):
      remaining_expense = signed_gross − linked payments
      gross_payable     = Σ positive remaining (aged by payment_date)
      credit_balance    = Σ −remaining where remaining < 0 (never aged)
      net_payable       = gross_payable − credit_balance

    *status_filter*: ``""`` | ``outstanding`` | ``overdue`` | ``credit``.
    *aging_bucket_filter*: optional bucket key to keep only suppliers with
    amount in that bucket.
    """
    df, dt = period if period else ("", "")
    ccy_f = (currency_filter or "").strip().upper()
    cid_f = (contractor_filter or "").strip()
    status_f = (status_filter or "").strip().lower()
    bucket_f = (aging_bucket_filter or "").strip()

    match = match_payments_to_expenses(expense_facts, payment_facts)
    paid_map: Dict[str, Decimal] = match["paid_against_expense"]
    warnings = list(match["warnings"])

    data_quality: Dict[str, int] = defaultdict(int)
    for w in warnings:
        ev = w.get("event") or "other"
        if ev == "zero_sentinel_object_references_ignored":
            data_quality[ev] += int(w.get("count") or 1)
        else:
            data_quality[ev] += 1

    seen_ids: set = set()
    CustKey = Tuple[str, str]
    cust: Dict[CustKey, Dict[str, Any]] = {}

    def _row(key: CustKey, name: str) -> Dict[str, Any]:
        if key not in cust:
            cust[key] = {
                "contractor_id": key[0],
                "supplier_name": name or "—",
                "currency": key[1],
                "buckets": _empty_buckets(),
                "credit_balance": Decimal("0"),
                "expense_count": 0,
                "open_expense_count": 0,
                "oldest_due_date": "",
                "days_oldest_overdue": 0,
                "last_expense_date": "",
                "last_payment_date": "",
                "gross_docs": Decimal("0"),
                "credits_docs": Decimal("0"),
                "payments_applied": Decimal("0"),
            }
        elif name and cust[key]["supplier_name"] in ("", "—"):
            cust[key]["supplier_name"] = name
        return cust[key]

    open_with_due = 0
    open_missing_due = 0
    expenses_with_due = 0
    expenses_missing_due = 0

    for exp in expense_facts:
        eid = exp.get("id") or ""
        if not eid:
            data_quality["expense_with_empty_id"] += 1
            continue
        if eid in seen_ids:
            data_quality["duplicate_expense_id"] += 1
            continue
        seen_ids.add(eid)

        cid = exp.get("contractor_id") or ""
        ccy = exp.get("currency") or ""
        if not cid:
            data_quality["missing_contractor_id"] += 1
            continue
        if not ccy:
            data_quality["unsupported_currency"] += 1
            continue
        if ccy_f and ccy != ccy_f:
            continue
        if cid_f and cid != cid_f:
            continue

        gross = exp.get("brutto")
        if gross is None:
            data_quality["malformed_amount"] += 1
            continue

        row = _row((cid, ccy), exp.get("contractor_name") or "")
        row["expense_count"] += 1
        if gross > 0:
            row["gross_docs"] += gross
        elif gross < 0:
            # Already-signed credit note / correction — never re-flip.
            row["credits_docs"] += -gross

        paid = paid_map.get(eid, Decimal("0"))
        rem = remaining_after_payments(gross, paid)
        row["payments_applied"] += paid

        edate = exp.get("date") or ""
        if edate and (not row["last_expense_date"] or edate > row["last_expense_date"]):
            row["last_expense_date"] = edate

        due = exp.get("payment_date") or ""
        if due:
            expenses_with_due += 1
        else:
            expenses_missing_due += 1

        if rem > 0:
            row["open_expense_count"] += 1
            if due:
                open_with_due += 1
                days = _days_between(as_of, due)
                bucket = _due_bucket(days)
                row["buckets"][bucket] += rem
                if not row["oldest_due_date"] or due < row["oldest_due_date"]:
                    row["oldest_due_date"] = due
                if days > row["days_oldest_overdue"]:
                    row["days_oldest_overdue"] = days
            else:
                open_missing_due += 1
                data_quality["missing_payment_date"] += 1
                row["buckets"]["due_date_unavailable"] += rem
        elif rem < 0:
            # Supplier credit / advance — outside overdue buckets.
            row["credit_balance"] += -rem

    exp_by_id = {f["id"]: f for f in expense_facts if f.get("id")}
    for p in payment_facts:
        if p["id"] not in match["matched_payment_ids"]:
            continue
        linked = p.get("linked_expense") or ""
        exp = exp_by_id.get(linked)
        if not exp:
            continue
        ccy = exp.get("currency") or ""
        cid = exp.get("contractor_id") or ""
        if ccy_f and ccy != ccy_f:
            continue
        if cid_f and cid != cid_f:
            continue
        key = (cid, ccy)
        if key not in cust:
            continue
        pd = p.get("date") or ""
        if pd and (not cust[key]["last_payment_date"] or pd > cust[key]["last_payment_date"]):
            cust[key]["last_payment_date"] = pd

    suppliers: List[Dict[str, Any]] = []
    for key, row in cust.items():
        buckets = row["buckets"]
        gross_payable = sum((buckets[b] for b in _BUCKETS), Decimal("0"))
        credit = row["credit_balance"]
        overdue = overdue_total(buckets)
        not_due = buckets["not_due"]
        net = gross_payable - credit

        if status_f == "outstanding" and gross_payable <= 0 and credit <= 0:
            continue
        if status_f == "overdue" and overdue <= 0:
            continue
        if status_f == "credit" and credit <= 0:
            continue
        if bucket_f:
            if bucket_f not in buckets or buckets[bucket_f] <= 0:
                continue

        suppliers.append({
            "contractor_id": row["contractor_id"],
            "supplier_name": row["supplier_name"],
            "currency": row["currency"],
            "gross_payable": _q(gross_payable),
            "credit_balance": _q(credit),
            "net_payable": _q(net),
            "not_due": _q(not_due),
            "b_1_30": _q(buckets["b_1_30"]),
            "b_31_60": _q(buckets["b_31_60"]),
            "b_61_90": _q(buckets["b_61_90"]),
            "b_91_180": _q(buckets["b_91_180"]),
            "b_181_365": _q(buckets["b_181_365"]),
            "b_365_plus": _q(buckets["b_365_plus"]),
            "due_date_unavailable": _q(buckets["due_date_unavailable"]),
            "overdue": _q(overdue),
            "oldest_due_date": row["oldest_due_date"] or None,
            "days_oldest_overdue": int(row["days_oldest_overdue"]),
            "last_expense_date": row["last_expense_date"] or None,
            "last_payment_date": row["last_payment_date"] or None,
            "expense_count": int(row["expense_count"]),
            "open_expense_count": int(row["open_expense_count"]),
            # Mirror of the AR block. ``net_payable`` is already the canonical
            # supplier-level net, so only the offset flag is derived — and, as
            # on the AR side, no "net 365+" is published without document-level
            # linkage proving which old expense a credit offsets.
            "offset_status": (
                "fully_offset" if credit >= gross and credit > 0
                else "partially_offset" if credit > 0
                else "actionable"
            ),
        })

    # Largest NET payable first; fully-offset positions last. Was
    # ``-overdue, -gross_payable`` — gross — so a supplier whose balance is
    # wholly offset by credit notes outranked one we genuinely owe.
    _OFFSET_RANK_AP = {"actionable": 0, "partially_offset": 1, "fully_offset": 2}
    suppliers.sort(
        key=lambda r: (
            _OFFSET_RANK_AP.get(r["offset_status"], 0),
            -Decimal(r["net_payable"]),
            -Decimal(r["overdue"]),
            r["supplier_name"] or "",
            r["contractor_id"] or "",
        )
    )

    by_ccy: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in suppliers:
        by_ccy[r["currency"]].append(r)

    currency_summaries: List[Dict[str, Any]] = []
    for ccy in sorted(by_ccy.keys()):
        rows = by_ccy[ccy]
        gp = sum((Decimal(r["gross_payable"]) for r in rows), Decimal("0"))
        cr = sum((Decimal(r["credit_balance"]) for r in rows), Decimal("0"))
        ovd = sum((Decimal(r["overdue"]) for r in rows), Decimal("0"))
        nd = sum((Decimal(r["not_due"]) for r in rows), Decimal("0"))
        buckets = _sum_buckets(rows)
        dua = buckets["due_date_unavailable"]
        aging_sum = sum(buckets.values(), Decimal("0"))
        currency_summaries.append({
            "currency": ccy,
            "gross_payable": _q(gp),
            "supplier_credits": _q(cr),
            "net_payable": _q(gp - cr),
            "overdue": _q(ovd),
            "not_due": _q(nd),
            "due_date_unavailable": _q(dua),
            "suppliers_outstanding": sum(
                1 for r in rows if Decimal(r["gross_payable"]) > 0
            ),
            "suppliers_overdue": sum(
                1 for r in rows if Decimal(r["overdue"]) > 0
            ),
            "suppliers_with_credit": sum(
                1 for r in rows if Decimal(r["credit_balance"]) > 0
            ),
            "oldest_overdue_days": max(
                (int(r["days_oldest_overdue"]) for r in rows), default=0
            ),
            "expenses_represented": sum(int(r["expense_count"]) for r in rows),
            "open_expenses": sum(int(r["open_expense_count"]) for r in rows),
            "aging_plus_unavailable": _q(aging_sum),
            "aging": {b: _q(v) for b, v in buckets.items()},
            "reconciliation_ok": aging_sum == gp,
        })

    open_total = open_with_due + open_missing_due
    due_coverage_pct = (
        round(100.0 * open_with_due / open_total, 2) if open_total else None
    )
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "generated_at": generated_at,
        "as_of": as_of,
        "period": {"from": df, "to": dt},
        "filters": {
            "currency": ccy_f or None,
            "contractor_id": cid_f or None,
            "status": status_f or None,
            "aging_bucket": bucket_f or None,
        },
        "source_health": source_health or {"ok": True},
        "currency_summaries": currency_summaries,
        "suppliers": suppliers,
        "data_quality": dict(data_quality),
        "due_date_coverage": {
            "expenses_with_payment_date": expenses_with_due,
            "expenses_missing_payment_date": expenses_missing_due,
            "open_with_payment_date": open_with_due,
            "open_missing_payment_date": open_missing_due,
            "open_coverage_pct": due_coverage_pct,
        },
        "query_stats": query_stats or {},
        "warnings": warnings[:200],
        "sign_convention": {
            "remaining_expense": "signed_gross - linked_payments",
            "gross_payable": "sum of positive remainings (aged)",
            "supplier_credits": "sum of -remaining where remaining < 0 (not aged)",
            "net_payable": "gross_payable - supplier_credits",
            "due_basis": "payment_date",
        },
    }


def build_payables_analysis(
    *,
    date_from: str,
    date_to: str,
    as_of: str = "",
    currency: str = "",
    contractor_id: str = "",
    status: str = "",
    aging_bucket: str = "",
    force_refresh: bool = False,
    source: str = "local",
    storage_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """AP portfolio — default local projection; live only on refresh/source=live."""
    df = (date_from or "").strip()
    dt = (date_to or "").strip()
    if not df or not dt:
        raise ValueError("date_from and date_to are required")
    if df > dt:
        raise ValueError(f"date_from {df!r} is after date_to {dt!r}")
    ao = (as_of or "").strip() or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    from .ledger_fact_universe import load_ap_fact_universe, timing_fields_from_universe

    src = (source or "local").strip().lower()
    if force_refresh:
        src = "live"
    if src not in ("local", "live"):
        raise ValueError("source must be local or live")

    provenance: Dict[str, Any] = {}
    if src == "local":
        from .local_fact_universe import (
            load_ap_fact_universe_local,
            local_projection_available,
        )
        from ..core.config import settings

        root = Path(storage_root) if storage_root else Path(settings.storage_root)
        ok, reason = local_projection_available(root)
        if not ok:
            raise LocalProjectionUnavailable(reason)
        uni = load_ap_fact_universe_local(root, df, dt)
        provenance = uni.get("provenance") or {}
    else:
        uni = load_ap_fact_universe(df, dt, force=force_refresh)
        provenance = {
            "source": "live",
            "freshness": "live",
            "reconciliation_status": "live_wfirma",
            "as_of_generated_at": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat(),
        }

    expense_facts = uni["expense_facts"]
    payment_facts = uni["payment_facts"]
    exp_stats = uni.get("exp_stats") or {}
    pay_stats = uni.get("pay_stats") or {}

    t_agg0 = time.perf_counter()
    query_stats = {
        "source": src,
        "expense_api_calls": int(exp_stats.get("api_calls") or 0),
        "payment_api_calls": int(pay_stats.get("api_calls") or 0),
        "expense_pages": int(exp_stats.get("pages") or 0),
        "payment_pages": int(pay_stats.get("pages") or 0),
        "expenses_normalized": len(expense_facts),
        "payments_normalized": len(payment_facts),
        "expense_duplicates_suppressed": int(
            exp_stats.get("duplicate_ids_suppressed") or 0
        ),
        "payment_duplicates_suppressed": int(
            pay_stats.get("duplicate_ids_suppressed") or 0
        ),
        "expense_stop_reason": exp_stats.get("stopped_reason"),
        "payment_stop_reason": pay_stats.get("stopped_reason"),
        "per_supplier_wfirma_calls": 0,
        "cache_hit": bool(uni.get("cache_hit")),
        "coalesced": bool(uni.get("coalesced")),
    }
    query_stats.update(timing_fields_from_universe(uni))
    health = {
        "ok": True,
        "source": src,
        "expense_cap_hit": exp_stats.get("stopped_reason") == "safety_cap",
        "payment_cap_hit": pay_stats.get("stopped_reason") == "safety_cap",
        "expense_paging_stalled": exp_stats.get("stopped_reason") == "no_new_ids",
        "payment_paging_stalled": pay_stats.get("stopped_reason") == "no_new_ids",
        "repeated_paging_page_detected": exp_stats.get("stopped_reason") == "no_new_ids"
        or pay_stats.get("stopped_reason") == "no_new_ids",
    }
    if health["expense_cap_hit"] or health["payment_cap_hit"]:
        health["ok"] = False
        health["note"] = "Safety cap hit — portfolio may be incomplete"
    if src == "local" and provenance.get("freshness") == "stale":
        health["note"] = "Local projection is stale — refresh for live reconciliation"

    portfolio = build_payables_portfolio_from_facts(
        expense_facts,
        payment_facts,
        as_of=ao,
        period=(df, dt),
        currency_filter=currency,
        contractor_filter=contractor_id,
        status_filter=status,
        aging_bucket_filter=aging_bucket,
        query_stats=query_stats,
        source_health=health,
    )
    ej_aggregate_ms = int((time.perf_counter() - t_agg0) * 1000)
    qs = portfolio.get("query_stats") or query_stats
    qs["ej_aggregate_ms"] = ej_aggregate_ms
    qs["ej_ms"] = int(qs.get("ej_normalize_ms") or 0) + ej_aggregate_ms
    portfolio["query_stats"] = qs
    portfolio["source"] = provenance.get("source") or src
    portfolio["freshness"] = provenance.get("freshness") or src
    portfolio["reconciliation_status"] = provenance.get("reconciliation_status")
    portfolio["projection"] = provenance.get("projection")
    return portfolio


__all__ = [
    "LocalProjectionUnavailable",
    "build_management_analysis",
    "build_portfolio_from_facts",
    "build_payables_analysis",
    "build_payables_portfolio_from_facts",
]
