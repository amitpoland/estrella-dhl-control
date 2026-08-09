"""
accounting_analytics.py — Phase 1 Management Analysis portfolio projection.
==========================================================================

Read-only receivables / debtor-aging projection over the SAME invoice and
payment facts consumed by Client Ledger (ledger_aggregator).

No wFirma writes. No second ledger DB. No FX consolidation across
USD/EUR/PLN. Aging uses invoice ``paymentdate`` (due date), never issue
date, for positive remainings.

Period semantics (identical to Client Ledger):
  • invoices included by issue date in [from, to]
  • payments included by payment date in [from, to]
  • window is never silently broadened
"""
from __future__ import annotations

import time
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

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


# Due-date aging buckets (Management Analysis). Distinct from the older
# statement invoice_age buckets (current/1_30/31_60/61_90/90_plus).
_BUCKETS = ("not_due", "b_1_30", "b_31_90", "b_91_180", "b_180_plus", "due_date_unavailable")


def _due_bucket(days_overdue: int) -> str:
    if days_overdue <= 0:
        return "not_due"
    if days_overdue <= 30:
        return "b_1_30"
    if days_overdue <= 90:
        return "b_31_90"
    if days_overdue <= 180:
        return "b_91_180"
    return "b_180_plus"


def _empty_buckets() -> Dict[str, Decimal]:
    return {b: Decimal("0") for b in _BUCKETS}


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

    match = match_payments_to_invoices(invoice_facts, payment_facts)
    paid_map: Dict[str, Decimal] = match["paid_against_invoice"]
    warnings = list(match["warnings"])

    data_quality: Dict[str, int] = defaultdict(int)
    for w in warnings:
        ev = w.get("event") or "other"
        data_quality[ev] += 1

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

    # Last payment date per customer from matched payments
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
        pd = p.get("date") or ""
        if pd and (not cust[key]["last_payment_date"] or pd > cust[key]["last_payment_date"]):
            cust[key]["last_payment_date"] = pd

    # Build customer rows + apply status filter
    customers: List[Dict[str, Any]] = []
    for key, row in cust.items():
        buckets = row["buckets"]
        receivable = sum((buckets[b] for b in _BUCKETS), Decimal("0"))
        credit = row["credit_balance"]
        outstanding = receivable  # positive AR only; credits separate
        overdue = (
            buckets["b_1_30"]
            + buckets["b_31_90"]
            + buckets["b_91_180"]
            + buckets["b_180_plus"]
        )
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
            "b_31_90": _q(buckets["b_31_90"]),
            "b_91_180": _q(buckets["b_91_180"]),
            "b_180_plus": _q(buckets["b_180_plus"]),
            "due_date_unavailable": _q(buckets["due_date_unavailable"]),
            "outstanding": _q(outstanding),
            "overdue": _q(overdue),
            "oldest_due_date": row["oldest_due_date"] or None,
            "days_oldest_overdue": int(row["days_oldest_overdue"]),
            "last_invoice_date": row["last_invoice_date"] or None,
            "last_payment_date": row["last_payment_date"] or None,
            "invoice_count": int(row["invoice_count"]),
            "open_invoice_count": int(row["open_invoice_count"]),
        })

    # Default sort: largest overdue DESC, then outstanding DESC
    customers.sort(
        key=lambda r: (
            -Decimal(r["overdue"]),
            -Decimal(r["outstanding"]),
            r["customer_name"] or "",
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
        dua = sum((Decimal(r["due_date_unavailable"]) for r in rows), Decimal("0"))
        # Invariant pieces
        aging_sum = (
            sum((Decimal(r["not_due"]) for r in rows), Decimal("0"))
            + sum((Decimal(r["b_1_30"]) for r in rows), Decimal("0"))
            + sum((Decimal(r["b_31_90"]) for r in rows), Decimal("0"))
            + sum((Decimal(r["b_91_180"]) for r in rows), Decimal("0"))
            + sum((Decimal(r["b_180_plus"]) for r in rows), Decimal("0"))
            + dua
        )
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


def build_management_analysis(
    *,
    date_from: str,
    date_to: str,
    as_of: str = "",
    currency: str = "",
    contractor_id: str = "",
    status: str = "",
    types: tuple = ("normal", "correction", "proforma"),
) -> Dict[str, Any]:
    """Live bulk portfolio read — ZERO per-customer wFirma calls."""
    df = (date_from or "").strip()
    dt = (date_to or "").strip()
    if not df or not dt:
        raise ValueError("date_from and date_to are required")
    if df > dt:
        raise ValueError(f"date_from {df!r} is after date_to {dt!r}")
    ao = (as_of or "").strip() or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    t0 = time.perf_counter()
    inv_stats: Dict[str, Any] = {}
    pay_stats: Dict[str, Any] = {}

    inv_nodes = wfirma_client.fetch_invoices_for_period(
        df, dt, types=types, stats=inv_stats
    )
    pay_nodes = wfirma_client.fetch_payments_for_period(df, dt, stats=pay_stats)

    inv_nodes = _python_filter_by_date(inv_nodes, df, dt, "date")
    pay_nodes = _python_filter_by_date(pay_nodes, df, dt, "date")

    invoice_facts = [_parse_invoice_fact(n) for n in inv_nodes]
    payment_facts = [_parse_payment_fact(n) for n in pay_nodes]

    duration_ms = int((time.perf_counter() - t0) * 1000)
    query_stats = {
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
        "duration_ms": duration_ms,
        "per_customer_wfirma_calls": 0,
    }
    health = {
        "ok": True,
        "invoice_cap_hit": inv_stats.get("stopped_reason") == "safety_cap",
        "payment_cap_hit": pay_stats.get("stopped_reason") == "safety_cap",
        "invoice_paging_stalled": inv_stats.get("stopped_reason") == "no_new_ids",
        "payment_paging_stalled": pay_stats.get("stopped_reason") == "no_new_ids",
    }
    if health["invoice_cap_hit"] or health["payment_cap_hit"]:
        health["ok"] = False
        health["note"] = "Safety cap hit — portfolio may be incomplete"

    return build_portfolio_from_facts(
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
        overdue = (
            buckets["b_1_30"]
            + buckets["b_31_90"]
            + buckets["b_91_180"]
            + buckets["b_180_plus"]
        )
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
            "b_31_90": _q(buckets["b_31_90"]),
            "b_91_180": _q(buckets["b_91_180"]),
            "b_180_plus": _q(buckets["b_180_plus"]),
            "due_date_unavailable": _q(buckets["due_date_unavailable"]),
            "overdue": _q(overdue),
            "oldest_due_date": row["oldest_due_date"] or None,
            "days_oldest_overdue": int(row["days_oldest_overdue"]),
            "last_expense_date": row["last_expense_date"] or None,
            "last_payment_date": row["last_payment_date"] or None,
            "expense_count": int(row["expense_count"]),
            "open_expense_count": int(row["open_expense_count"]),
        })

    suppliers.sort(
        key=lambda r: (
            -Decimal(r["overdue"]),
            -Decimal(r["gross_payable"]),
            r["supplier_name"] or "",
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
        dua = sum((Decimal(r["due_date_unavailable"]) for r in rows), Decimal("0"))
        aging_sum = (
            nd
            + sum((Decimal(r["b_1_30"]) for r in rows), Decimal("0"))
            + sum((Decimal(r["b_31_90"]) for r in rows), Decimal("0"))
            + sum((Decimal(r["b_91_180"]) for r in rows), Decimal("0"))
            + sum((Decimal(r["b_180_plus"]) for r in rows), Decimal("0"))
            + dua
        )
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
) -> Dict[str, Any]:
    """Live bulk AP portfolio — ZERO per-supplier wFirma calls."""
    df = (date_from or "").strip()
    dt = (date_to or "").strip()
    if not df or not dt:
        raise ValueError("date_from and date_to are required")
    if df > dt:
        raise ValueError(f"date_from {df!r} is after date_to {dt!r}")
    ao = (as_of or "").strip() or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    t0 = time.perf_counter()
    exp_stats: Dict[str, Any] = {}
    pay_stats: Dict[str, Any] = {}

    exp_nodes = wfirma_client.fetch_expenses_for_period(df, dt, stats=exp_stats)
    pay_nodes = wfirma_client.fetch_payments_for_period(df, dt, stats=pay_stats)

    exp_nodes = _python_filter_by_date(exp_nodes, df, dt, "date")
    pay_nodes = _python_filter_by_date(pay_nodes, df, dt, "date")

    expense_facts = [_parse_expense_fact(n) for n in exp_nodes]
    payment_facts = [_parse_payment_fact(n) for n in pay_nodes]

    duration_ms = int((time.perf_counter() - t0) * 1000)
    query_stats = {
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
        "duration_ms": duration_ms,
        "per_supplier_wfirma_calls": 0,
    }
    if int(exp_stats.get("duplicate_ids_suppressed") or 0):
        # Surface into data_quality via source_health note; portfolio builder
        # also counts duplicate ids if any slip through.
        pass
    health = {
        "ok": True,
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

    return build_payables_portfolio_from_facts(
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


__all__ = [
    "build_management_analysis",
    "build_portfolio_from_facts",
    "build_payables_analysis",
    "build_payables_portfolio_from_facts",
]
