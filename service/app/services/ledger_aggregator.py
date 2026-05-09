"""
ledger_aggregator.py — Phase 10A pure-data aggregator.
=====================================================

Turns a list of wFirma ``<invoice>`` Element nodes into a chronological
per-currency invoice ledger. **No payments. No aging. No balances.**

This is intentionally a thinner output than a Statement of Account.
Phase 10A.5 must run a live probe of ``payments/find`` and the invoice
``<paymentstate>`` / ``<alreadypaid>`` / ``<remaining>`` / ``<paid_date>``
fields BEFORE any aging or balance work begins. Until that probe lands,
this module only surfaces the seven invoice-side fields proven by
``app/tools/sync_customer_invoice_snapshot.py:270-288``:

    wfirma_doc_id   — <id>
    doc_number      — <fullnumber>
    type            — <type>            (normal | correction | proforma)
    date            — <date>
    currency        — <currency>
    total_net       — <netto>
    total_gross     — <brutto>

All decimals are emitted as quantised-2dp strings so JSON consumers do
not lose precision through float round-trips. Chronological order
within each currency bucket: ``date`` ascending, ``wfirma_doc_id``
ascending as the deterministic tie-break.

The aggregator is pure: no I/O, no DB, no HTTP. It is unit-testable
with synthetic XML fixtures.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Tuple
import xml.etree.ElementTree as ET


# Fields the aggregator emits per entry — pinned by the Phase 10A test
# ``test_entries_contain_exactly_seven_proven_fields``. Keep this tuple
# in lockstep with the entry dict below; any change is a contract break.
LEDGER_ENTRY_FIELDS: Tuple[str, ...] = (
    "wfirma_doc_id",
    "doc_number",
    "type",
    "date",
    "currency",
    "total_net",
    "total_gross",
)

# Fields the aggregator MUST NEVER emit on any entry — neither
# Phase 10A invoice-ledger entries nor Phase 10B Statement entries.
#
# Phase 10A originally pinned the operator-friendly snake_case forms
# (`payment_state`, `due_date`, `paid_date`); Phase 10B adds the
# wFirma-native one-word forms (`paymentstate`, `paymentdate`) so the
# aggregator can never accidentally surface either spelling. The
# Statement of Account (Phase 10B) computes ``remaining`` LOCALLY
# from payments — the wFirma-side `remaining` / `alreadypaid` fields
# remain forbidden as inputs and as outputs until a real-id probe
# verifies them (see ``docs/PHASE10B_STATEMENT_ARCHITECTURE.md`` §3).
FORBIDDEN_ENTRY_FIELDS: Tuple[str, ...] = (
    "payment_state",
    "paymentstate",
    "remaining",
    "alreadypaid",
    "due_date",
    "paymentdate",
    "paid_date",
    "aging",
)


def _decimal_or_none(text: str) -> Decimal:
    """Parse a wFirma decimal string. Returns Decimal('0') for empty /
    unparseable values — ledger emission must never fail because one
    invoice has a missing total."""
    s = (text or "").strip()
    if not s:
        return Decimal("0")
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _q(d: Decimal) -> str:
    """Quantise to 2dp and stringify. JSON consumers parse strings as
    Decimal-equivalent without float drift."""
    return str(d.quantize(Decimal("0.01")))


def _entry_from_invoice(inv: ET.Element) -> Dict[str, Any]:
    """Project one ``<invoice>`` node into a ledger entry dict.

    Only emits the seven proven fields. Empty / missing source values
    surface as empty strings (``date``, ``doc_number``, ``currency``)
    or ``"0.00"`` (totals); callers downstream can drop / surface them
    as they like.
    """
    return {
        "wfirma_doc_id": (inv.findtext("id") or "").strip(),
        "doc_number":    (inv.findtext("fullnumber") or "").strip(),
        "type":          (inv.findtext("type") or "").strip(),
        "date":          (inv.findtext("date") or "").strip(),
        "currency":      (inv.findtext("currency") or "").strip().upper(),
        "total_net":     _q(_decimal_or_none(inv.findtext("netto"))),
        "total_gross":   _q(_decimal_or_none(inv.findtext("brutto"))),
    }


def aggregate_invoice_ledger(
    contractor_meta: Dict[str, Any],
    invoice_nodes:   List[ET.Element],
    period:          Tuple[str, str],
) -> Dict[str, Any]:
    """Build the JSON-serialisable invoice ledger.

    Parameters
    ----------
    contractor_meta : dict
        At minimum ``wfirma_contractor_id``. Optional: ``name``,
        ``country``, ``vat_id``. Surfaced verbatim on the response so
        the route can carry through what ``fetch_contractor_by_id``
        already returned without a second fetch.
    invoice_nodes : list[Element]
        Output of ``wfirma_client.fetch_invoices_for_contractor``.
        The route MUST have already date-filtered this list Python-side
        per the rules in that helper's docstring (wFirma can return
        out-of-window invoices).
    period : (date_from, date_to)
        Echoed into the response so consumers know the requested
        window — does NOT trigger another date filter here.

    Returns
    -------
    dict
        ``{
          "contractor": {...},
          "period": {"from": ..., "to": ...},
          "currencies": [...],          # sorted unique currency codes
          "entries_per_currency": {     # chronological per currency
            "EUR": [<entry>, ...],
            "USD": [<entry>, ...],
            ...
          },
          "totals_per_currency": {      # invoice totals only — no balance
            "EUR": {"invoiced_net": "...", "invoiced_gross": "...",
                     "entry_count": int},
            ...
          }
        }``
    """
    df, dt = period if period else ("", "")

    entries_by_ccy: Dict[str, List[Dict[str, Any]]] = {}
    for inv in invoice_nodes or []:
        e = _entry_from_invoice(inv)
        # Skip entries with no id — they are unusable as ledger rows.
        if not e["wfirma_doc_id"]:
            continue
        ccy = e["currency"] or "PLN"   # fallback only for the bucket key
        entries_by_ccy.setdefault(ccy, []).append(e)

    # Sort each currency bucket: date asc, then wfirma_doc_id asc.
    for ccy, rows in entries_by_ccy.items():
        rows.sort(key=lambda r: (r["date"], r["wfirma_doc_id"]))

    totals_by_ccy: Dict[str, Dict[str, Any]] = {}
    for ccy, rows in entries_by_ccy.items():
        net   = sum((Decimal(r["total_net"])   for r in rows), Decimal("0"))
        gross = sum((Decimal(r["total_gross"]) for r in rows), Decimal("0"))
        totals_by_ccy[ccy] = {
            "invoiced_net":   _q(net),
            "invoiced_gross": _q(gross),
            "entry_count":    len(rows),
        }

    return {
        "contractor": {
            "wfirma_contractor_id": str(
                contractor_meta.get("wfirma_contractor_id") or ""
            ),
            "name":     str(contractor_meta.get("name")    or ""),
            "country":  str(contractor_meta.get("country") or ""),
            "vat_id":   str(contractor_meta.get("vat_id")  or ""),
        },
        "period": {
            "from": str(df or ""),
            "to":   str(dt or ""),
        },
        "currencies": sorted(entries_by_ccy.keys()),
        "entries_per_currency": entries_by_ccy,
        "totals_per_currency":  totals_by_ccy,
    }


# ════════════════════════════════════════════════════════════════════════
#  Phase 10B — Statement of Account
# ════════════════════════════════════════════════════════════════════════
#
# Pure data model + algorithm. No I/O. Consumes:
#   contractor_meta : dict   (preflight result from fetch_contractor_by_id)
#   invoice_nodes   : list[ET.Element]  (from fetch_invoices_for_contractor)
#   payment_nodes   : list[ET.Element]  (from fetch_payments_for_contractor)
#   statement_date  : str    (YYYY-MM-DD; aging anchor)
#   period          : (from, to)         (echoed; caller already filtered)
#
# Pin spec: docs/PHASE10B_STATEMENT_ARCHITECTURE.md
#
# Reconciliation rule (§6 of the spec):
#   remaining_for(X) = X.brutto
#                       - Σ payment.value
#                         where payment.invoice/id == X.id
#                           AND payment.currency_label == X.currency
# Cross-currency payment-vs-invoice mismatch → payment is unmatched.
# Empty payment.invoice/id           → payment is unmatched.
# Negative <brutto> on a correction  → contributes to totals.credited.
# Aging hardcoded to "invoice_age"   → label exposed on every block.

# Entry types in chronological output. Numeric tie-break rank below
# enforces invoice-before-same-day-payment ordering (§5.1 of the spec).
_ENTRY_TYPE_RANK = {
    "invoice":    0,
    "correction": 1,
    "proforma":   2,
    "payment":    3,
}

# Aging bucket labels in their stable JSON order. Pinned by tests.
_AGING_BUCKETS = ("current", "1_30", "31_60", "61_90", "90_plus")


def _bucket_for_days(days_old: int) -> str:
    if days_old <= 0:
        return "current"
    if days_old <= 30:
        return "1_30"
    if days_old <= 60:
        return "31_60"
    if days_old <= 90:
        return "61_90"
    return "90_plus"


def _empty_aging() -> Dict[str, str]:
    out = {b: "0.00" for b in _AGING_BUCKETS}
    out["total"] = "0.00"
    return out


def _days_between(later: str, earlier: str) -> int:
    """Both arguments are ``YYYY-MM-DD``. Returns ``later - earlier`` in
    days. Empty / unparseable inputs yield 0 — the caller already filters
    those rows from the aging path."""
    from datetime import date
    try:
        a = date.fromisoformat(later)
        b = date.fromisoformat(earlier)
    except Exception:
        return 0
    return (a - b).days


def _parse_invoice_fact(inv: ET.Element) -> Dict[str, Any]:
    """Project an <invoice> node into the verified-fields-only dict the
    Statement aggregator works with."""
    return {
        "id":            (inv.findtext("id") or "").strip(),
        "fullnumber":    (inv.findtext("fullnumber") or "").strip(),
        "type":          (inv.findtext("type") or "").strip(),
        "date":          (inv.findtext("date") or "").strip(),
        "currency":      (inv.findtext("currency") or "").strip().upper(),
        "netto":         _decimal_or_none(inv.findtext("netto")),
        "brutto":        _decimal_or_none(inv.findtext("brutto")),
        "contractor_id": (inv.findtext("contractor/id") or "").strip(),
    }


def _parse_payment_fact(pay: ET.Element) -> Dict[str, Any]:
    """Project a <payment> node into the verified-fields-only dict.

    Only the six fields confirmed by the Phase 10A.5 live probe are read:
    id, invoice/id, value, value_pln, date, currency_label. Every other
    leaf (account, payment_method, compensation_*, payroll fields, etc.)
    is ignored — the Statement does not need them.
    """
    return {
        "id":              (pay.findtext("id") or "").strip(),
        "linked_invoice":  (pay.findtext("invoice/id") or "").strip(),
        "value":           _decimal_or_none(pay.findtext("value")),
        "value_pln":       _decimal_or_none(pay.findtext("value_pln")),
        "date":            (pay.findtext("date") or "").strip(),
        "currency":        (pay.findtext("currency_label") or "").strip().upper(),
    }


def _invoice_signed_debit_credit(fact: Dict[str, Any]) -> tuple:
    """Return ``(debit, credit)`` Decimals for an invoice fact.

    ``correction`` rows may carry a negative ``<brutto>`` (credit note);
    the negative amount becomes a credit and contributes to
    totals.credited. Regular invoices and proformas are positive debits.
    """
    brutto = fact["brutto"]
    if fact["type"] == "correction" and brutto < 0:
        return (Decimal("0"), -brutto)
    return (brutto, Decimal("0"))


def _entry_for_invoice(fact: Dict[str, Any]) -> Dict[str, Any]:
    debit, credit = _invoice_signed_debit_credit(fact)
    # Map wFirma <type> to the Statement entry type. Anything we don't
    # recognise falls back to "invoice" with a warning emitted upstream.
    typ = fact["type"]
    if typ not in ("invoice", "correction", "proforma", "normal"):
        typ = "invoice"
    if typ == "normal":
        typ = "invoice"
    return {
        "type":            typ,
        "wfirma_doc_id":   fact["id"],
        "doc_number":      fact["fullnumber"],
        "date":            fact["date"],
        "currency":        fact["currency"],
        "debit":           _q(debit),
        "credit":          _q(credit),
        # running_balance filled in by the chronological walk
        "running_balance": "0.00",
    }


def _entry_for_payment(
    fact:        Dict[str, Any],
    is_unmatched: bool,
) -> Dict[str, Any]:
    """Entry shape for a payment.

    A negative ``<value>`` represents a payment reversal in wFirma. We
    treat it as a debit (positive) on the running balance — money
    returned to the customer. The unmatched-payment listing is keyed
    by `is_unmatched` so the dashboard can render it separately.
    """
    value = fact["value"]
    if value < 0:
        debit, credit = (-value, Decimal("0"))
    else:
        debit, credit = (Decimal("0"), value)
    return {
        "type":            "payment",
        "wfirma_doc_id":   fact["id"],
        "doc_number":      "",
        "linked_invoice":  fact["linked_invoice"] if not is_unmatched else "",
        "date":            fact["date"],
        "currency":        fact["currency"],
        "debit":           _q(debit),
        "credit":          _q(credit),
        "running_balance": "0.00",
    }


def aggregate_statement(
    contractor_meta: Dict[str, Any],
    invoice_nodes:   List[ET.Element],
    payment_nodes:   List[ET.Element],
    statement_date:  str,
    period:          tuple,
) -> Dict[str, Any]:
    """Build the per-currency Statement of Account.

    Pure: no I/O, no DB, no HTTP. Caller is responsible for date-filtering
    invoice and payment nodes Python-side BEFORE calling this — the
    aggregator does not re-filter (so bucketing matches the fetched
    window exactly).

    Returns the data model documented in
    ``docs/PHASE10B_STATEMENT_ARCHITECTURE.md`` §4. All decimals are
    quantised-2dp strings.
    """
    df, dt = period if period else ("", "")
    warnings: List[Dict[str, Any]] = []

    invoice_facts = [_parse_invoice_fact(n) for n in (invoice_nodes or [])]
    payment_facts = [_parse_payment_fact(n) for n in (payment_nodes or [])]

    # Drop unusable rows; warn if we dropped anything.
    invoice_facts_kept: List[Dict[str, Any]] = []
    for f in invoice_facts:
        if not f["id"]:
            warnings.append({"event": "invoice_with_empty_id"})
            continue
        if not f["currency"]:
            warnings.append({
                "event":         "invoice_currency_missing",
                "wfirma_doc_id": f["id"],
            })
        if f["type"] == "proforma":
            warnings.append({
                "event":         "proforma_treated_as_debit",
                "wfirma_doc_id": f["id"],
            })
        invoice_facts_kept.append(f)
    invoice_facts = invoice_facts_kept

    payment_facts_kept: List[Dict[str, Any]] = []
    for f in payment_facts:
        if not f["id"]:
            warnings.append({"event": "payment_with_empty_id"})
            continue
        if not f["currency"]:
            warnings.append({
                "event":         "payment_currency_missing",
                "wfirma_doc_id": f["id"],
            })
            continue   # cannot bucket — skip from per-currency totals
        if f["value"] < 0:
            warnings.append({
                "event":         "reversal_payment",
                "wfirma_doc_id": f["id"],
            })
        payment_facts_kept.append(f)
    payment_facts = payment_facts_kept

    # Build invoice index by (id, currency) for the §6 reconciliation.
    invoice_by_id: Dict[str, Dict[str, Any]] = {f["id"]: f for f in invoice_facts}

    # Classify each payment as matched (currency-aligned with linked
    # invoice) or unmatched. paid_against_invoice maps id → Decimal sum
    # of currency-aligned matched payments only.
    paid_against_invoice: Dict[str, Decimal] = {}
    unmatched_payments_by_ccy: Dict[str, List[Dict[str, Any]]] = {}
    matched_payment_ids: set = set()

    for p in payment_facts:
        linked = p["linked_invoice"]
        ccy    = p["currency"] or "PLN"
        is_unmatched = False
        if not linked:
            is_unmatched = True
            warnings.append({
                "event":         "unmatched_payment",
                "wfirma_doc_id": p["id"],
            })
        else:
            inv = invoice_by_id.get(linked)
            if inv is None:
                # Linked invoice not in the fetched window. We don't
                # know its currency; treat as unmatched in the
                # payment's own currency.
                is_unmatched = True
                warnings.append({
                    "event":          "payment_links_invoice_outside_window",
                    "wfirma_doc_id":  p["id"],
                    "linked_invoice": linked,
                })
            elif (inv["currency"] or "").upper() != p["currency"]:
                is_unmatched = True
                warnings.append({
                    "event":              "currency_mismatch_with_invoice",
                    "wfirma_doc_id":      p["id"],
                    "linked_invoice":     linked,
                    "invoice_currency":   inv["currency"],
                    "payment_currency":   p["currency"],
                })
            else:
                matched_payment_ids.add(p["id"])
                paid_against_invoice[linked] = (
                    paid_against_invoice.get(linked, Decimal("0")) + p["value"]
                )

        if is_unmatched:
            unmatched_payments_by_ccy.setdefault(ccy, []).append({
                "wfirma_doc_id":   p["id"],
                "value":           _q(p["value"]),
                "currency":        p["currency"],
                "date":            p["date"],
                "linked_invoice":  linked,
            })

    # Detect overpayments per invoice — an invoice whose currency-aligned
    # matched payments exceed brutto.
    for inv_id, paid in paid_against_invoice.items():
        inv = invoice_by_id[inv_id]
        if paid > inv["brutto"] and inv["brutto"] > 0:
            warnings.append({
                "event":          "overpayment_on_invoice",
                "wfirma_doc_id":  inv_id,
                "invoice_total":  _q(inv["brutto"]),
                "amount_paid":    _q(paid),
                "overpaid_by":    _q(paid - inv["brutto"]),
            })

    # ── Build per-currency entry lists with chronological tie-break ───
    entries_by_ccy: Dict[str, List[Dict[str, Any]]] = {}
    currencies: set = set()

    for f in invoice_facts:
        ccy = f["currency"] or "PLN"
        currencies.add(ccy)
        entries_by_ccy.setdefault(ccy, []).append(_entry_for_invoice(f))

    # Re-walk payments to know which were unmatched, so the entry's
    # linked_invoice field is blanked appropriately.
    matched_set = matched_payment_ids
    for p in payment_facts:
        ccy = p["currency"] or "PLN"
        currencies.add(ccy)
        is_unmatched = p["id"] not in matched_set
        entries_by_ccy.setdefault(ccy, []).append(
            _entry_for_payment(p, is_unmatched=is_unmatched)
        )

    # Sort each currency bucket by (date, type rank, doc_id).
    for ccy, rows in entries_by_ccy.items():
        rows.sort(key=lambda r: (
            r["date"],
            _ENTRY_TYPE_RANK.get(r["type"], 99),
            r["wfirma_doc_id"],
        ))
        # Compute running balance.
        running = Decimal("0")
        for e in rows:
            running += Decimal(e["debit"]) - Decimal(e["credit"])
            e["running_balance"] = _q(running)

    # ── Per-currency totals ────────────────────────────────────────────
    totals_by_ccy: Dict[str, Dict[str, Any]] = {}
    for ccy, rows in entries_by_ccy.items():
        invoiced = Decimal("0")
        credited = Decimal("0")
        received = Decimal("0")
        for e in rows:
            d = Decimal(e["debit"])
            c = Decimal(e["credit"])
            if e["type"] in ("invoice", "correction", "proforma"):
                invoiced += d
                credited += c
            elif e["type"] == "payment":
                received += c
                # Negative payments ("reversal") added a debit; subtract
                # from received to keep the "money received" total honest.
                received -= d
        outstanding = invoiced - credited - received
        totals_by_ccy[ccy] = {
            "invoiced":    _q(invoiced),
            "credited":    _q(credited),
            "received":    _q(received),
            "outstanding": _q(outstanding),
            "entry_count": len(rows),
        }

    # ── Aging per currency (invoice_age method) ───────────────────────
    aging_by_ccy: Dict[str, Dict[str, Any]] = {}
    for ccy in sorted(currencies):
        bucket: Dict[str, Decimal] = {b: Decimal("0") for b in _AGING_BUCKETS}
        total = Decimal("0")
        # Walk invoices in this currency only — payments don't age.
        for inv in invoice_facts:
            if (inv["currency"] or "PLN") != ccy:
                continue
            if not inv["date"]:
                continue
            paid = paid_against_invoice.get(inv["id"], Decimal("0"))
            # Treat correction credit notes (negative brutto) as already
            # reducing balance; their "remaining" is their absolute
            # signed value but it's already credited at invoice time.
            # We only age positive-balance invoices.
            remaining = inv["brutto"] - paid
            if remaining <= 0:
                continue
            days_old = _days_between(statement_date, inv["date"])
            b = _bucket_for_days(days_old)
            bucket[b] += remaining
            total += remaining
        aging_by_ccy[ccy] = {
            "method":  "invoice_age",
            **{k: _q(v) for k, v in bucket.items()},
            "total":   _q(total),
        }

    return {
        "contractor": {
            "wfirma_contractor_id": str(
                contractor_meta.get("wfirma_contractor_id") or ""
            ),
            "name":     str(contractor_meta.get("name")    or ""),
            "country":  str(contractor_meta.get("country") or ""),
            "vat_id":   str(contractor_meta.get("vat_id")  or ""),
        },
        "generated_at":   statement_date,
        "period":         {"from": str(df or ""), "to": str(dt or "")},
        "currencies":     sorted(currencies),
        "entries_per_currency":          entries_by_ccy,
        "totals_per_currency":           totals_by_ccy,
        "aging_per_currency":            aging_by_ccy,
        "unmatched_payments_per_currency": unmatched_payments_by_ccy,
        "warnings":       warnings,
    }


__all__ = [
    "LEDGER_ENTRY_FIELDS",
    "FORBIDDEN_ENTRY_FIELDS",
    "aggregate_invoice_ledger",
    # Phase 10B
    "aggregate_statement",
]
