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
from typing import Any, Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET

from .financial_aging import (
    AGING_BUCKETS,
    due_bucket as _due_bucket_canonical,
    open_total as _open_total_canonical,
)


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
    # due_date IS emitted as an operator column (derived from paymentdate).
    # The raw wFirma spelling ``paymentdate`` must never appear on the wire.
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
        "total_gross":   _q(_decimal_or_none(_invoice_gross_raw(inv))),
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
# Reconciliation rule (§6 — corrected 2026-08-09 live probe):
#   remaining_for(X) = X.brutto
#                       - Σ payment.value
#                         where payment.invoice/id == X.id
#
# Payment XML has **no ISO currency tag**. ``currency_label`` is an NBP
# table reference (e.g. ``083/A/NBP/2021``) or empty — never treat it as
# USD/EUR/PLN. Matched payments inherit the linked invoice's ISO currency.
# Cross-currency invent via currency_label is forbidden (no FX fallback).
# Empty payment.invoice/id           → payment is unmatched.
# Negative <brutto> on a correction  → contributes to totals.credited.
# Aging default ``due_date`` (invoice ``paymentdate``) — same canonical
# basis as Management Analysis. ``invoice_age`` only when the caller
# passes that method explicitly (no silent per-surface mix).
#
# Statement period semantics (Tally-style carried balances):
#   Caller loads invoice facts from the configured history floor through
#   period ``to``, and payments through ``to`` (no lower bound). The
#   aggregator then:
#     • matches payments against the FULL invoice set (so a payment in
#       the activity window can settle an invoice from before ``from``);
#     • computes OPENING = net of all matched movements with date < from;
#     • lists only movements with date in [from, to] as period activity;
#     • runs the balance from opening → closing.
#   Payments that still cannot match any loaded invoice remain unmatched.
#   Opening is never invented as zero when prior history is present.

AGING_METHOD_DUE_DATE = "due_date"
AGING_METHOD_INVOICE_AGE = "invoice_age"
_AGING_METHODS = (AGING_METHOD_DUE_DATE, AGING_METHOD_INVOICE_AGE)

# The aging buckets are built from POSITIVE remainings only — credit notes
# and over-settled documents are never aged (the same rule the receivables
# and payables portfolios use). The buckets are therefore GROSS, before
# credits, and the renderer is required to say so. Emitted on every
# statement as ``aging_basis`` so a UI cannot quietly present a gross
# overdue figure as if it were the net position.
AGING_BASIS_GROSS = "gross_before_credits"

# Entry types in chronological output. Numeric tie-break rank below
# enforces invoice-before-same-day-payment ordering (§5.1 of the spec).
_ENTRY_TYPE_RANK = {
    "opening_balance": -1,
    "invoice":    0,
    "correction": 1,
    "proforma":   2,
    "payment":    3,
}

# Aging bucket labels in their stable JSON order. Canonical set from
# financial_aging (MA / Client Balance / Statement parity).
_AGING_BUCKETS = AGING_BUCKETS


def _bucket_for_days(days_old: int) -> str:
    """Map days-overdue (or invoice age) to a canonical aging key."""
    return _due_bucket_canonical(days_old)


def _empty_aging() -> Dict[str, str]:
    out = {b: "0.00" for b in _AGING_BUCKETS}
    out["total"] = "0.00"
    return out


# ── Presentation state (display only — never a second accounting engine) ──
# Canonical identity lives in accounting_analytics.py:545-546:
#     credit_balance = Σ −remaining where remaining < 0   (never aged)
#     net            = gross − credit_balance
# These helpers only NAME the result of that identity for the operator.
# routes_ledgers delegates to them so there is exactly one implementation.

def presentation_state(gross: Any, credits: Any) -> str:
    """Display state from canonical Gross / Credits. Not a second engine.

    open    = Gross > 0 and Net > 0
    offset  = Gross > 0 and Net == 0 (credits fully cover gross)
    credit  = Gross == 0 and Credits > 0
    clear   = Gross == 0 and Credits == 0
    """
    g = _dec_or_zero(gross)
    cr = _dec_or_zero(credits)
    net = g - cr
    if g > 0 and net == 0:
        return "offset"
    if g == 0 and cr > 0:
        return "credit"
    if g > 0:
        return "open"
    return "clear"


def presentation_state_from_maps(
    gross_by: Dict[str, Any],
    credit_by: Dict[str, Any],
) -> str:
    """Per-currency presentation roll-up. Never FX-sums amounts.

    Each currency leg is evaluated independently and the portfolio state is
    the most-open leg: a fully offset USD leg does not clear an open EUR leg.
    """
    any_open = False
    any_offset = False
    any_credit = False
    keys = set(gross_by or {}) | set(credit_by or {})
    if not keys:
        return "clear"
    for ccy in keys:
        st = presentation_state(
            (gross_by or {}).get(ccy), (credit_by or {}).get(ccy)
        )
        if st == "open":
            any_open = True
        elif st == "offset":
            any_offset = True
        elif st == "credit":
            any_credit = True
    if any_open:
        return "open"
    if any_offset:
        return "offset"
    if any_credit:
        return "credit"
    return "clear"


def _dec_or_zero(v: Any) -> Decimal:
    if isinstance(v, Decimal):
        return v
    try:
        return Decimal(str(v or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


# Operator-facing row status vocabulary. Emitted as ``presentation_status``
# alongside the legacy ``status`` key so screen and PDF read ONE backend
# field and never re-derive status in JavaScript.
PRESENTATION_STATUS_BF = "B/F"
PRESENTATION_STATUS_NOT_DUE = "Not Due"
PRESENTATION_STATUS_OVERDUE = "Overdue"
PRESENTATION_STATUS_SETTLED = "Settled"
PRESENTATION_STATUS_CREDIT = "Credit / Offset"
PRESENTATION_STATUS_APPLIED = "Applied"
PRESENTATION_STATUS_UNAPPLIED = "Unapplied"
PRESENTATION_STATUS_DUE_UNAVAILABLE = "Due Date Unavailable"
PRESENTATION_STATUS_CONFLICT = "Status Conflict"

# wFirma source values that claim the document is settled. The source claim is
# NEVER displayed; it is only compared against the locally computed economic
# remaining.
_SOURCE_CLAIMS_SETTLED = frozenset({"paid", "settled"})


def derive_presentation_status(
    *,
    entry_type: str,
    remaining: Optional[Decimal] = None,
    due_date: str = "",
    as_of: str = "",
    is_credit_document: bool = False,
    is_unmatched: bool = False,
    source_payment_state: str = "",
    has_explaining_correction: bool = False,
) -> str:
    """Derive the operator-facing row status. Backend authority — never React.

    Economic remaining decides settlement; the source lifecycle flag is only
    ever used to detect DISAGREEMENT between source and economics.

    ``Status Conflict`` fires when the source claims the document is paid but
    the economic remaining is still positive AND no correction document
    explains the difference. The correction check is mandatory: measured
    against production on 2026-08-18, 47/47 AR and 6/6 AP candidate conflicts
    were fully explained by a linked correction — a correction-blind rule
    raises 53 false alarms and zero true ones.
    """
    if entry_type == "opening_balance":
        return PRESENTATION_STATUS_BF
    if entry_type == "payment":
        return (
            PRESENTATION_STATUS_UNAPPLIED if is_unmatched
            else PRESENTATION_STATUS_APPLIED
        )
    if is_credit_document:
        return PRESENTATION_STATUS_CREDIT
    rem = _dec_or_zero(remaining)
    claims_settled = (source_payment_state or "").strip().lower() in _SOURCE_CLAIMS_SETTLED
    if claims_settled and rem > 0 and not has_explaining_correction:
        return PRESENTATION_STATUS_CONFLICT
    if rem <= 0:
        return PRESENTATION_STATUS_SETTLED
    due = (due_date or "").strip()
    if not due:
        return PRESENTATION_STATUS_DUE_UNAVAILABLE
    if as_of and due < as_of:
        return PRESENTATION_STATUS_OVERDUE
    return PRESENTATION_STATUS_NOT_DUE


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


def _is_iso_currency_code(raw: Optional[str]) -> bool:
    """True only for a 3-letter alphabetic ISO code (USD/EUR/PLN…)."""
    s = (raw or "").strip().upper()
    return len(s) == 3 and s.isalpha()


def _iso_currency_or_empty(raw: Optional[str]) -> str:
    s = (raw or "").strip().upper()
    return s if _is_iso_currency_code(s) else ""


def remaining_after_payments(gross: Decimal, paid: Decimal) -> Decimal:
    """Shared remaining = signed gross − matched payments (no FX).

    Used by Client Ledger (AR) and Supplier AP — same Decimal equation.
    """
    return gross - paid


def _normalize_doc_link_id(raw: Optional[str]) -> str:
    """Normalize wFirma document link ids.

    Live AP audit (2026-08-09): ``invoice/id=0`` and ``expense/id=0`` are
    no-link sentinels, not valid object references. Empty / whitespace /
    literal ``"0"`` → empty string.
    """
    s = (raw or "").strip()
    if not s or s == "0":
        return ""
    return s


def _invoice_gross_raw(inv: ET.Element) -> Optional[str]:
    """Document-currency gross — same authority as accounting_documents.

    Domestic invoices expose ``<brutto>``. Foreign-currency (WDT) invoices
    often omit ``brutto`` and put the document-currency gross in ``<total>``
    (``<netto>`` may be PLN). Payment ``<value>`` matches document currency.
    """
    for tag in ("brutto", "total", "total_brutto"):
        raw = inv.findtext(tag)
        if raw is not None and str(raw).strip() != "":
            return raw
    return None


def _parse_invoice_fact(inv: ET.Element) -> Dict[str, Any]:
    """Project an <invoice> node into the verified-fields-only dict the
    Statement aggregator works with."""
    name = (
        (inv.findtext("contractor_detail/name") or "").strip()
        or (inv.findtext("contractor/name") or "").strip()
    )
    return {
        "id":              (inv.findtext("id") or "").strip(),
        "fullnumber":      (inv.findtext("fullnumber") or "").strip(),
        "type":            (inv.findtext("type") or "").strip(),
        "date":            (inv.findtext("date") or "").strip(),
        "paymentdate":     (inv.findtext("paymentdate") or "").strip(),
        "currency":        _iso_currency_or_empty(inv.findtext("currency")),
        "netto":           _decimal_or_none(inv.findtext("netto")),
        "brutto":          _decimal_or_none(_invoice_gross_raw(inv)),
        "contractor_id":   (inv.findtext("contractor/id") or "").strip(),
        "contractor_name": name,
        # Source lifecycle flag — INTERNAL ONLY. ``payment_state`` /
        # ``paymentstate`` are in FORBIDDEN_ENTRY_FIELDS and must never reach
        # the wire; they exist here solely so the aggregator can compare the
        # source claim against the locally computed economic remaining and
        # derive a "Status Conflict" presentation status. Empty when wFirma
        # does not emit the tag — the conflict rule then simply never fires.
        "payment_state":   (inv.findtext("paymentstate") or "").strip(),
        # Correction linkage. A correction that fully offsets its parent is a
        # legitimate reason for "source says paid, remaining > 0" — without
        # this link the conflict rule produces false alarms.
        "correction_of_id": _normalize_doc_link_id(inv.findtext("parent/id")),
    }


def _parse_payment_fact(pay: ET.Element) -> Dict[str, Any]:
    """Project a <payment> node into the verified-fields-only dict.

    Live payment schema (2026-08-09): id, invoice/id, expense/id, value,
    value_pln, date, currency_label, currency_date, currency_exchange —
    **no** ``<currency>`` ISO tag. ``currency_label`` is an NBP table id
    when present (e.g. ``083/A/NBP/2021``) and must never be copied into
    the ISO ``currency`` field.

    ``invoice/id=0`` and ``expense/id=0`` are no-link sentinels.
    """
    label = (pay.findtext("currency_label") or "").strip()
    # Optional defence: if a future schema adds <currency>, accept only ISO.
    raw_currency = pay.findtext("currency")
    return {
        "id":              (pay.findtext("id") or "").strip(),
        "linked_invoice":  _normalize_doc_link_id(pay.findtext("invoice/id")),
        "linked_expense":  _normalize_doc_link_id(pay.findtext("expense/id")),
        "value":           _decimal_or_none(pay.findtext("value")),
        "value_pln":       _decimal_or_none(pay.findtext("value_pln")),
        "date":            (pay.findtext("date") or "").strip(),
        "currency_label":  label,  # NBP / FX table reference — not ISO
        "currency":        _iso_currency_or_empty(raw_currency),
        "contractor_id":   (pay.findtext("contractor/id") or "").strip(),
    }


def _expense_gross_raw(exp: ET.Element) -> Optional[str]:
    """Document-currency expense gross — prefer ``brutto``, then ``total``."""
    for tag in ("brutto", "total", "total_brutto"):
        raw = exp.findtext(tag)
        if raw is not None and str(raw).strip() != "":
            return raw
    return None


# --- AP document lifecycle classification (single authority) ---------------
# wFirma expense lifecycle lives in <draft> + <is_rejected>, NOT in <status>
# (the expenses module never emits <status>). Documents reaching the expense
# inbox via the UBL 2.1 e-invoice parser start as drafts and are then either
# accepted into the books (draft=0) or rejected (draft=2, is_rejected=1).
# A rejected inbox document is not a booked liability and must never enter the
# AP open-payable universe.
EXPENSE_CLASS_BOOKED = "booked"
EXPENSE_CLASS_DRAFT = "draft"
EXPENSE_CLASS_REJECTED = "rejected"


def classify_expense_lifecycle(draft: str, is_rejected: str) -> str:
    """Classify a wFirma expense by its source lifecycle flags.

    The ONE authority for "is this expense a booked liability?". Both the live
    universe (``load_ap_fact_universe``) and the local projection mapper
    (``sync_financial_reporting.map_expense_node``) call this — never their own
    copy of the rule.

    ``rejected``: wFirma itself rejected the inbound document. Never a payable.
    ``draft``:    in the inbox, not yet booked. Still a real supplier document,
                  so it stays in the universe but is disclosed as unbooked.
    ``booked``:   posted to the books. A payable.
    """
    d = (draft or "").strip()
    r = (is_rejected or "").strip()
    if r == "1":
        return EXPENSE_CLASS_REJECTED
    if d not in ("", "0"):
        return EXPENSE_CLASS_DRAFT
    return EXPENSE_CLASS_BOOKED


def _parse_expense_fact(exp: ET.Element) -> Dict[str, Any]:
    """Project an <expense> node into the AP ExpenseFact dict.

    Live expense schema (2026-08-09 scoped audit): due date is
    ``payment_date`` (underscore), not invoice ``paymentdate``.
    ``correction=1`` credit notes already carry signed negative ``brutto``.
    ``lifecycle`` carries the ``classify_expense_lifecycle`` verdict.
    """
    name = (
        (exp.findtext("contractor_detail/name") or "").strip()
        or (exp.findtext("contractor/name") or "").strip()
    )
    corr_raw = (exp.findtext("correction") or "").strip()
    return {
        "id":              (exp.findtext("id") or "").strip(),
        "fullnumber":      (exp.findtext("fullnumber") or exp.findtext("number") or "").strip(),
        "type":            (exp.findtext("type") or "").strip(),
        "date":            (exp.findtext("date") or "").strip(),
        "payment_date":    (exp.findtext("payment_date") or "").strip(),
        "currency":        _iso_currency_or_empty(exp.findtext("currency")),
        "netto":           _decimal_or_none(exp.findtext("netto")),
        "brutto":          _decimal_or_none(_expense_gross_raw(exp)),
        "contractor_id":   (exp.findtext("contractor/id") or "").strip(),
        "contractor_name": name,
        "paymentstate":    (exp.findtext("paymentstate") or "").strip(),
        # Normalised aliases — same field names as the AR fact so the shared
        # presentation-status rule reads one key on both sides.
        "payment_state":   (exp.findtext("paymentstate") or "").strip(),
        "correction":      corr_raw,
        "parent_id":       _normalize_doc_link_id(exp.findtext("parent/id")),
        "correction_of_id": _normalize_doc_link_id(exp.findtext("parent/id")),
        "lifecycle":       classify_expense_lifecycle(
            exp.findtext("draft") or "", exp.findtext("is_rejected") or ""
        ),
    }


def match_payments_to_invoices(
    invoice_facts: List[Dict[str, Any]],
    payment_facts: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Shared payment→invoice apply step for Client Ledger and analytics.

    Returns:
      paid_against_invoice: id → Decimal sum of matched payment values
      matched_payment_ids: set
      unmatched_payments: list of payment facts (outside window / no link /
        ISO mismatch)
      warnings: list of event dicts (same event names as aggregate_statement)
    """
    warnings: List[Dict[str, Any]] = []
    invoice_by_id = {f["id"]: f for f in invoice_facts if f.get("id")}
    paid_against_invoice: Dict[str, Decimal] = {}
    matched_payment_ids: set = set()
    unmatched_payments: List[Dict[str, Any]] = []

    for p in payment_facts:
        if not p.get("id"):
            warnings.append({"event": "payment_with_empty_id"})
            continue
        linked = _normalize_doc_link_id(p.get("linked_invoice"))
        if not linked:
            unmatched_payments.append(p)
            warnings.append({
                "event": "unmatched_payment",
                "wfirma_doc_id": p["id"],
            })
            continue
        inv = invoice_by_id.get(linked)
        if inv is None:
            unmatched_payments.append(p)
            warnings.append({
                "event": "payment_links_invoice_outside_window",
                "wfirma_doc_id": p["id"],
                "linked_invoice": linked,
            })
            continue
        inherited = inv.get("currency") or ""
        pay_iso = p.get("currency") or ""
        if pay_iso and inherited and pay_iso != inherited:
            unmatched_payments.append(p)
            warnings.append({
                "event": "currency_mismatch_with_invoice",
                "wfirma_doc_id": p["id"],
                "linked_invoice": linked,
                "invoice_currency": inherited,
                "payment_currency": pay_iso,
            })
            continue
        p = dict(p)
        p["currency"] = inherited or pay_iso
        matched_payment_ids.add(p["id"])
        paid_against_invoice[linked] = (
            paid_against_invoice.get(linked, Decimal("0")) + p["value"]
        )
        inv_cid = inv.get("contractor_id") or ""
        pay_cid = p.get("contractor_id") or ""
        if inv_cid and pay_cid and inv_cid != pay_cid:
            warnings.append({
                "event": "payment_invoice_contractor_mismatch",
                "wfirma_doc_id": p["id"],
                "linked_invoice": linked,
                "invoice_contractor_id": inv_cid,
                "payment_contractor_id": pay_cid,
            })

    return {
        "paid_against_invoice": paid_against_invoice,
        "matched_payment_ids": matched_payment_ids,
        "unmatched_payments": unmatched_payments,
        "warnings": warnings,
    }


def match_payments_to_expenses(
    expense_facts: List[Dict[str, Any]],
    payment_facts: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Shared payment→expense apply step for Supplier AP / Creditor Aging.

    Matches only on normalized ``linked_expense`` (never names). Expense
    ISO currency owns the payment currency context unless the payment
    carries a conflicting real ISO ``<currency>`` (then refuse match).
    """
    warnings: List[Dict[str, Any]] = []
    expense_by_id = {f["id"]: f for f in expense_facts if f.get("id")}
    paid_against_expense: Dict[str, Decimal] = {}
    matched_payment_ids: set = set()
    unmatched_payments: List[Dict[str, Any]] = []
    ignored_sentinel_links = 0

    for p in payment_facts:
        if not p.get("id"):
            warnings.append({"event": "payment_with_empty_id"})
            continue
        raw_linked = str(p.get("linked_expense") or "").strip()
        if raw_linked == "0":
            ignored_sentinel_links += 1
        linked = _normalize_doc_link_id(raw_linked)
        if not linked:
            # Expense-unlinked (AR invoice payment or neither) — not an AP match.
            unmatched_payments.append(p)
            continue
        exp = expense_by_id.get(linked)
        if exp is None:
            unmatched_payments.append(p)
            warnings.append({
                "event": "orphan_expense_payment",
                "wfirma_doc_id": p["id"],
                "linked_expense": linked,
            })
            continue
        inherited = exp.get("currency") or ""
        pay_iso = p.get("currency") or ""
        if pay_iso and inherited and pay_iso != inherited:
            unmatched_payments.append(p)
            warnings.append({
                "event": "currency_mismatch_with_expense",
                "wfirma_doc_id": p["id"],
                "linked_expense": linked,
                "expense_currency": inherited,
                "payment_currency": pay_iso,
            })
            continue
        if p["id"] in matched_payment_ids:
            warnings.append({
                "event": "duplicate_payment_id_ignored",
                "wfirma_doc_id": p["id"],
                "linked_expense": linked,
            })
            continue
        p = dict(p)
        p["currency"] = inherited or pay_iso
        p["linked_expense"] = linked
        matched_payment_ids.add(p["id"])
        paid_against_expense[linked] = (
            paid_against_expense.get(linked, Decimal("0")) + (p.get("value") or Decimal("0"))
        )
        exp_cid = exp.get("contractor_id") or ""
        pay_cid = p.get("contractor_id") or ""
        if exp_cid and pay_cid and exp_cid != pay_cid:
            warnings.append({
                "event": "payment_expense_contractor_mismatch",
                "wfirma_doc_id": p["id"],
                "linked_expense": linked,
                "expense_contractor_id": exp_cid,
                "payment_contractor_id": pay_cid,
            })

    if ignored_sentinel_links:
        warnings.append({
            "event": "zero_sentinel_object_references_ignored",
            "count": ignored_sentinel_links,
        })

    return {
        "paid_against_expense": paid_against_expense,
        "matched_payment_ids": matched_payment_ids,
        "unmatched_payments": unmatched_payments,
        "warnings": warnings,
    }


def aggregate_supplier_statement(
    expense_facts: List[Dict[str, Any]],
    payment_facts: List[Dict[str, Any]],
    *,
    contractor_meta: Optional[Dict[str, Any]] = None,
    period: Tuple[str, str] = ("", ""),
    as_of: str = "",
) -> Dict[str, Any]:
    """Read-only Supplier Ledger statement from the same AP facts.

    Chronological movements per currency. Remaining uses
    :func:`remaining_after_payments` — no second arithmetic authority.
    """
    meta = contractor_meta or {}
    df, dt = period if period else ("", "")
    match = match_payments_to_expenses(expense_facts, payment_facts)
    paid_map: Dict[str, Decimal] = match["paid_against_expense"]
    matched_ids = match["matched_payment_ids"]
    warnings = list(match["warnings"])

    expense_by_id = {f["id"]: f for f in expense_facts if f.get("id")}
    entries_by_ccy: Dict[str, List[Dict[str, Any]]] = {}

    # Parents that already carry an explaining correction document. The
    # supplier side needs this for exactly the same reason the client side
    # does: a source ``paid`` flag against a positive remaining is only a
    # Status Conflict when nothing explains the difference.
    corrected_parent_ids = {
        str(f.get("correction_of_id") or f.get("parent_id") or "")
        for f in expense_facts
        if (f.get("correction") or "").strip() not in ("", "0")
    }
    corrected_parent_ids.discard("")

    for f in expense_facts:
        if not f.get("id") or not f.get("currency"):
            continue
        ccy = f["currency"]
        gross = f.get("brutto") or Decimal("0")
        if gross >= 0:
            debit, credit = gross, Decimal("0")
            typ = "expense"
        else:
            debit, credit = Decimal("0"), -gross
            typ = "credit_note"
        rem = remaining_after_payments(gross, paid_map.get(f["id"], Decimal("0")))
        if rem > 0:
            status = "open"
        elif rem < 0:
            status = "credit"
        else:
            status = "settled"
        parent = str(f.get("correction_of_id") or f.get("parent_id") or "")
        entries_by_ccy.setdefault(ccy, []).append({
            "type": typ,
            "wfirma_doc_id": f["id"],
            "doc_number": f.get("fullnumber") or "",
            "date": f.get("date") or "",
            "due_date": f.get("payment_date") or "",
            "reference": (
                (expense_by_id.get(parent) or {}).get("fullnumber") or parent
            ) if parent else "",
            "currency": ccy,
            "debit": _q(debit),
            "credit": _q(credit),
            "running_balance": "0.00",
            "status": status,
            # ``presentation_status`` — the SAME backend authority the client
            # ledger uses. ``rem`` here is the value the legacy ``status`` above
            # was already computed from, so this names an existing result; it
            # opens no second settlement path. ``remaining`` itself is in
            # FORBIDDEN_ENTRY_FIELDS and never rides on the emitted row.
            "presentation_status": derive_presentation_status(
                entry_type="invoice",
                remaining=rem,
                due_date=f.get("payment_date") or "",
                as_of=as_of,
                is_credit_document=(typ == "credit_note"),
                source_payment_state=(
                    f.get("payment_state") or f.get("paymentstate") or ""
                ),
                has_explaining_correction=(f["id"] in corrected_parent_ids),
            ),
            "correction": f.get("correction") or "",
        })

    for p in payment_facts:
        if p.get("id") not in matched_ids:
            continue
        linked = _normalize_doc_link_id(p.get("linked_expense"))
        exp = expense_by_id.get(linked) if linked else None
        ccy = (exp.get("currency") if exp else "") or (p.get("currency") or "")
        if not ccy:
            continue
        val = p.get("value") or Decimal("0")
        if val >= 0:
            debit, credit = Decimal("0"), val
        else:
            debit, credit = -val, Decimal("0")
        entries_by_ccy.setdefault(ccy, []).append({
            "type": "payment",
            "wfirma_doc_id": p["id"],
            "doc_number": "",
            "date": p.get("date") or "",
            "due_date": "",
            "reference": (
                (exp or {}).get("fullnumber") or linked
            ) if linked else "",
            "currency": ccy,
            "debit": _q(debit),
            "credit": _q(credit),
            "running_balance": "0.00",
            "status": "applied",
            "presentation_status": derive_presentation_status(
                entry_type="payment", is_unmatched=not linked,
            ),
            "linked_expense": linked,
            "correction": "",
        })

    # Tally-style opening / period / closing. Remaining / aging stay on the
    # FULL loaded expense set (history floor → period.to) using
    # remaining_after_payments + expense/id knock-off — no second matching path.
    period_from = str(df or "")
    period_to = str(dt or "")

    def _in_period(date_s: str) -> bool:
        d = (date_s or "").strip()
        if not d:
            return False
        if period_from and d < period_from:
            return False
        if period_to and d > period_to:
            return False
        return True

    def _before_period(date_s: str) -> bool:
        d = (date_s or "").strip()
        if not d or not period_from:
            return False
        return d < period_from

    opening_by_ccy: Dict[str, Decimal] = {}
    period_entries_by_ccy: Dict[str, List[Dict[str, Any]]] = {}
    for ccy, rows in entries_by_ccy.items():
        rows.sort(key=lambda r: (
            r["date"], 0 if r["type"] != "payment" else 1, r["wfirma_doc_id"],
        ))
        opening = Decimal("0")
        period_rows: List[Dict[str, Any]] = []
        for e in rows:
            delta = Decimal(e["debit"]) - Decimal(e["credit"])
            d = e.get("date") or ""
            if _before_period(d):
                opening += delta
            elif _in_period(d):
                period_rows.append(e)
        opening_by_ccy[ccy] = opening
        running = opening
        for e in period_rows:
            running += Decimal(e["debit"]) - Decimal(e["credit"])
            e["running_balance"] = _q(running)
        display_rows: List[Dict[str, Any]] = []
        if opening != 0 or any(_before_period(e.get("date") or "") for e in rows):
            bf_debit = opening if opening > 0 else Decimal("0")
            bf_credit = (-opening) if opening < 0 else Decimal("0")
            display_rows.append({
                "type": "opening_balance",
                "wfirma_doc_id": "",
                "doc_number": "OPENING BALANCE / B/F",
                "date": period_from or "",
                # A carried-forward balance has no due date of its own.
                "due_date": "",
                "reference": "",
                "currency": ccy,
                "debit": _q(bf_debit),
                "credit": _q(bf_credit),
                "running_balance": _q(opening),
                "status": "B/F",
                "presentation_status": PRESENTATION_STATUS_BF,
                "source": "carried",
                "is_opening_balance": True,
                "correction": "",
            })
        display_rows.extend(period_rows)
        period_entries_by_ccy[ccy] = display_rows

    entries_by_ccy = period_entries_by_ccy

    unmatched_by_ccy: Dict[str, List[Dict[str, Any]]] = {}
    meta_cid = str(meta.get("wfirma_contractor_id") or "")
    for p in match.get("unmatched_payments") or []:
        # AR invoice-linked payments are not supplier unapplied.
        if _normalize_doc_link_id(p.get("linked_invoice")):
            continue
        pay_cid = str(p.get("contractor_id") or "")
        if meta_cid and pay_cid and pay_cid != meta_cid:
            continue
        # An expense link that resolved to nothing (orphan, outside the
        # window, or a currency the expense contradicts) is still OUR cash,
        # paid to THIS supplier. It was previously dropped here as "already
        # in warnings" -- but warnings are a diagnostic stream, so the money
        # vanished from the only document the supplier actually reads, while
        # the AR side disclosed the mirror case. Disclosed now, with the link
        # it names, so the gap is visible and reconcilable rather than silent.
        ccy = (p.get("currency") or "").strip().upper() or "UNRESOLVED"
        unmatched_by_ccy.setdefault(ccy, []).append({
            "wfirma_doc_id": p.get("id") or "",
            "value": _q(p.get("value") or Decimal("0")),
            "currency": ccy if ccy != "UNRESOLVED" else "",
            "date": p.get("date") or "",
            "linked_expense": _normalize_doc_link_id(p.get("linked_expense")),
            # See the AR note: unapplied cash is reported, never netted in.
            "due_date":            "",
            "reference":           "",
            "presentation_status": PRESENTATION_STATUS_UNAPPLIED,
        })

    totals_by_ccy: Dict[str, Dict[str, Any]] = {}
    for ccy, rows in entries_by_ccy.items():
        period_rows = [e for e in rows if not e.get("is_opening_balance")]
        opening = opening_by_ccy.get(ccy, Decimal("0"))
        period_debits = sum((Decimal(e["debit"]) for e in period_rows), Decimal("0"))
        period_credits = sum((Decimal(e["credit"]) for e in period_rows), Decimal("0"))
        closing = opening + period_debits - period_credits
        gross_pay = Decimal("0")
        credits = Decimal("0")
        paid = Decimal("0")
        for f in expense_facts:
            if (f.get("currency") or "") != ccy:
                continue
            g = f.get("brutto") or Decimal("0")
            if g > 0:
                gross_pay += g
            elif g < 0:
                credits += -g
            paid += paid_map.get(f["id"], Decimal("0"))
        outstanding = remaining_after_payments(gross_pay - credits, paid)
        # Prefer sum of positive remainings − credit balances for clarity
        pos = Decimal("0")
        credit_bal = Decimal("0")
        for f in expense_facts:
            if (f.get("currency") or "") != ccy:
                continue
            rem = remaining_after_payments(
                f.get("brutto") or Decimal("0"),
                paid_map.get(f["id"], Decimal("0")),
            )
            if rem > 0:
                pos += rem
            elif rem < 0:
                credit_bal += -rem
        net_payable = pos - credit_bal
        if abs(closing - net_payable) > Decimal("0.005"):
            warnings.append({
                "event": "supplier_statement_closing_invariant_drift",
                "currency": ccy,
                "closing": _q(closing),
                "net_payable": _q(net_payable),
            })
        totals_by_ccy[ccy] = {
            "opening_balance": _q(opening),
            "period_debits": _q(period_debits),
            "period_credits": _q(period_credits),
            "closing_balance": _q(closing),
            "gross_payable": _q(gross_pay),
            "supplier_credits": _q(credits if credits else credit_bal),
            "payments_applied": _q(paid),
            "outstanding": _q(pos),
            "credit_balance": _q(credit_bal),
            "net_payable": _q(net_payable),
            "entry_count": len(period_rows),
            "formula_outstanding": _q(outstanding),
        }

    # Due-date aging on the SAME remainings the totals above are built from,
    # using the SAME bucket boundaries as the payables portfolio (imported, not
    # re-derived — a second bucket definition would drift). Supplier credits
    # stay outside the overdue buckets, exactly as in build_payables_analysis.
    # Local import: accounting_analytics imports this module, so a module-level
    # import here would be circular.
    from .accounting_analytics import _BUCKETS, _due_bucket

    aging_by_ccy: Dict[str, Dict[str, Any]] = {}
    for ccy in entries_by_ccy:
        buckets = {b: Decimal("0") for b in _BUCKETS}
        for f in expense_facts:
            if (f.get("currency") or "") != ccy:
                continue
            rem = remaining_after_payments(
                f.get("brutto") or Decimal("0"),
                paid_map.get(f["id"], Decimal("0")),
            )
            if rem <= 0:
                continue
            due = f.get("payment_date") or ""
            if due and as_of:
                buckets[_due_bucket(_days_between(as_of, due))] += rem
            else:
                buckets["due_date_unavailable"] += rem
        out = {b: _q(v) for b, v in buckets.items()}
        out["total"] = _q(sum(buckets.values(), Decimal("0")))
        out["method"] = "due_date"
        out["aging_basis"] = AGING_BASIS_GROSS
        aging_by_ccy[ccy] = out

    # ── POSITION per currency (as-of economic position) ────────────────
    # Same contract as the client statement so ONE renderer serves both.
    # Nothing is recomputed here: gross / credits / net come straight from
    # the totals block above, overdue is what the buckets already say.
    position_by_ccy: Dict[str, Dict[str, Any]] = {}
    for ccy, tot in totals_by_ccy.items():
        ag = aging_by_ccy.get(ccy) or {}
        not_due = Decimal(str(ag.get("not_due") or "0"))
        unavailable = Decimal(str(ag.get("due_date_unavailable") or "0"))
        aged_total = Decimal(str(ag.get("total") or "0"))
        gross_open = Decimal(str(tot["outstanding"]))
        credit_open = Decimal(str(tot["credit_balance"]))
        position_by_ccy[ccy] = {
            "gross_exposure":       tot["outstanding"],
            "supplier_credits":     tot["credit_balance"],
            "credit_balance":       tot["credit_balance"],
            "net_position":         tot["net_payable"],
            "overdue":              _q(aged_total - not_due - unavailable),
            "not_due":              _q(not_due),
            "due_date_unavailable": _q(unavailable),
            "aging_basis":          AGING_BASIS_GROSS,
            "presentation_state":   presentation_state(gross_open, credit_open),
        }

    return {
        "contractor": {
            "wfirma_contractor_id": str(meta.get("wfirma_contractor_id") or ""),
            "name": str(meta.get("name") or ""),
            "country": str(meta.get("country") or ""),
            "vat_id": str(meta.get("vat_id") or ""),
            "street": str(meta.get("street") or ""),
            "city": str(meta.get("city") or ""),
            "postal_code": str(meta.get("postal_code") or ""),
        },
        "generated_at": as_of or "",
        "as_of": as_of or "",
        "period": {"from": str(df or ""), "to": str(dt or "")},
        "currencies": sorted(entries_by_ccy.keys()),
        "entries_per_currency": entries_by_ccy,
        "totals_per_currency": totals_by_ccy,
        "position_per_currency": position_by_ccy,
        "aging_per_currency": aging_by_ccy,
        "unmatched_payments_per_currency": unmatched_by_ccy,
        "presentation_state": presentation_state_from_maps(
            {c: Decimal(str(t["outstanding"])) for c, t in totals_by_ccy.items()},
            {c: Decimal(str(t["credit_balance"])) for c, t in totals_by_ccy.items()},
        ),
        "aging_basis": AGING_BASIS_GROSS,
        "warnings": warnings,
        "query_stats": {"per_supplier_wfirma_calls": 0},
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
        # Operator-facing due column — derived from verified paymentdate.
        # Raw wFirma spelling ``paymentdate`` stays off the wire (FORBIDDEN).
        "due_date":        (fact.get("paymentdate") or "").strip(),
        # Operator cross-reference column. Filled by the enrichment walk with
        # the counterpart document (a correction points at its parent); stays
        # empty for a plain invoice.
        "reference":       "",
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
        # A payment has no due date of its own — the column renders as an
        # em dash. Never substitute the payment date here.
        "due_date":        "",
        # Filled by the enrichment walk with the settled invoice number.
        "reference":       "",
        "currency":        fact["currency"],
        "debit":           _q(debit),
        "credit":          _q(credit),
        "running_balance": "0.00",
    }


def _normalize_aging_method(aging_method: str) -> str:
    m = (aging_method or "").strip().lower()
    if m in _AGING_METHODS:
        return m
    return AGING_METHOD_DUE_DATE


def aggregate_statement_from_facts(
    contractor_meta: Dict[str, Any],
    invoice_facts:   List[Dict[str, Any]],
    payment_facts:   List[Dict[str, Any]],
    statement_date:  str,
    period:          tuple,
    *,
    aging_method: str = AGING_METHOD_DUE_DATE,
) -> Dict[str, Any]:
    """Build the per-currency Statement of Account from parsed facts.

    Pure: no I/O. Same arithmetic as :func:`aggregate_statement` — the
    node-based entrypoint parses then delegates here so bulk AR roster
    and single-contractor drill share one authority.

    *aging_method*: ``due_date`` (default — invoice ``paymentdate``, MA
    parity) or ``invoice_age`` (explicit opt-in only).
    """
    df, dt = period if period else ("", "")
    method = _normalize_aging_method(aging_method)
    warnings: List[Dict[str, Any]] = []

    # Drop unusable rows; warn if we dropped anything.
    invoice_facts_kept: List[Dict[str, Any]] = []
    for f in invoice_facts or []:
        if not f.get("id"):
            warnings.append({"event": "invoice_with_empty_id"})
            continue
        if not f.get("currency"):
            warnings.append({
                "event":         "invoice_currency_missing",
                "wfirma_doc_id": f["id"],
            })
        if f.get("type") == "proforma":
            # Proforma is commercial — never fiscal AR. Silent defensive
            # drop (fiscal callers already exclude via FISCAL_AR_INVOICE_TYPES;
            # do not emit a customer-facing warning for a boundary miss).
            continue
        invoice_facts_kept.append(f)
    invoice_facts = invoice_facts_kept

    payment_facts_kept: List[Dict[str, Any]] = []
    for f in payment_facts or []:
        if not f.get("id"):
            warnings.append({"event": "payment_with_empty_id"})
            continue
        # Mutating currency inheritance below must not leak across callers.
        f = dict(f)
        if f.get("value", Decimal("0")) < 0:
            warnings.append({
                "event":         "reversal_payment",
                "wfirma_doc_id": f["id"],
            })
        payment_facts_kept.append(f)
    payment_facts = payment_facts_kept

    # Build invoice index by id for the §6 reconciliation.
    invoice_by_id: Dict[str, Dict[str, Any]] = {f["id"]: f for f in invoice_facts}

    # Parents that a correction document in this universe points at. A parent
    # in this set has a documented reason for "source says paid while the
    # economic remaining is still positive", so it is NOT a status conflict.
    corrected_parent_ids: set = {
        str(f.get("correction_of_id") or "")
        for f in invoice_facts
        if str(f.get("correction_of_id") or "")
    }

    # Classify each payment as matched (linked invoice in window) or
    # unmatched. paid_against_invoice maps id → Decimal sum of matched
    # payments only. Matched payments inherit the invoice ISO currency.
    paid_against_invoice: Dict[str, Decimal] = {}
    unmatched_payments_by_ccy: Dict[str, List[Dict[str, Any]]] = {}
    matched_payment_ids: set = set()

    for p in payment_facts:
        linked = _normalize_doc_link_id(p.get("linked_invoice"))
        if not linked and _normalize_doc_link_id(p.get("linked_expense")):
            # Supplier-side cash. The AP statement owns it -- matched there,
            # or disclosed there as unapplied. Reporting it here as well would
            # show one payment on two statements as two different things, and
            # would tell the customer we hold money of theirs that we do not.
            # Exact mirror of the guard in the AP bucketing loop below.
            continue
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
                # Linked invoice not in the fetched window. Do not broaden
                # the window; keep the outside-window warning.
                is_unmatched = True
                warnings.append({
                    "event":          "payment_links_invoice_outside_window",
                    "wfirma_doc_id":  p["id"],
                    "linked_invoice": linked,
                })
            else:
                # Match on invoice id. Payment value is in document currency.
                inherited_ccy = inv.get("currency") or ""
                if not inherited_ccy:
                    warnings.append({
                        "event":         "invoice_currency_missing",
                        "wfirma_doc_id": inv["id"],
                    })
                # If payment somehow carries a real ISO <currency> that
                # disagrees with the invoice, refuse the match (no FX).
                pay_iso = p.get("currency") or ""
                if pay_iso and inherited_ccy and pay_iso != inherited_ccy:
                    is_unmatched = True
                    warnings.append({
                        "event":              "currency_mismatch_with_invoice",
                        "wfirma_doc_id":      p["id"],
                        "linked_invoice":     linked,
                        "invoice_currency":   inherited_ccy,
                        "payment_currency":   pay_iso,
                    })
                else:
                    p["currency"] = inherited_ccy or pay_iso
                    matched_payment_ids.add(p["id"])
                    paid_against_invoice[linked] = (
                        paid_against_invoice.get(linked, Decimal("0")) + p["value"]
                    )

        if is_unmatched:
            # Bucket key: payment ISO if present, else UNRESOLVED — never
            # NBP currency_label.
            ccy = p.get("currency") or ""
            if not ccy:
                ccy = "UNRESOLVED"
                warnings.append({
                    "event":         "payment_currency_unresolved",
                    "wfirma_doc_id": p["id"],
                    "currency_label": p.get("currency_label") or "",
                })
            unmatched_payments_by_ccy.setdefault(ccy, []).append({
                "wfirma_doc_id":   p["id"],
                "value":           _q(p["value"]),
                "currency":        ccy if ccy != "UNRESOLVED" else "",
                "currency_label":  p.get("currency_label") or "",
                "date":            p["date"],
                "linked_invoice":  linked,
                # Unapplied cash. It is NOT an entry — it does not move the
                # running balance and must not silently reduce the closing
                # figure. It is reported in its own block, with the same
                # backend-supplied status vocabulary the rows use.
                "due_date":            "",
                "reference":           "",
                "presentation_status": PRESENTATION_STATUS_UNAPPLIED,
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

    # Fiscal entries: matched payments only. Proforma-only (or other
    # non-fiscal / outside-window) links stay in unmatched_payments_*
    # and must not reduce fiscal received / outstanding / running balance.
    matched_set = matched_payment_ids
    for p in payment_facts:
        if p["id"] not in matched_set:
            continue
        ccy = p["currency"] or "PLN"
        currencies.add(ccy)
        entries_by_ccy.setdefault(ccy, []).append(
            _entry_for_payment(p, is_unmatched=False)
        )

    # Sort each currency bucket by (date, type rank, doc_id).
    for ccy, rows in entries_by_ccy.items():
        rows.sort(key=lambda r: (
            r["date"],
            _ENTRY_TYPE_RANK.get(r["type"], 99),
            r["wfirma_doc_id"],
        ))

    # ── Tally-style opening / period / closing split ───────────────────
    # Opening = net of movements dated strictly before period.from.
    # Period movements = dates in [from, to]. Running balance starts at
    # opening so contiguous periods satisfy previous_closing == next_opening.
    period_from = str(df or "")
    period_to = str(dt or "")

    def _in_period(date_s: str) -> bool:
        d = (date_s or "").strip()
        if not d:
            return False
        if period_from and d < period_from:
            return False
        if period_to and d > period_to:
            return False
        return True

    def _before_period(date_s: str) -> bool:
        d = (date_s or "").strip()
        if not d or not period_from:
            return False
        return d < period_from

    opening_by_ccy: Dict[str, Decimal] = {}
    period_entries_by_ccy: Dict[str, List[Dict[str, Any]]] = {}
    for ccy, rows in entries_by_ccy.items():
        opening = Decimal("0")
        period_rows: List[Dict[str, Any]] = []
        for e in rows:
            d = e.get("date") or ""
            delta = Decimal(e["debit"]) - Decimal(e["credit"])
            if _before_period(d):
                opening += delta
            elif _in_period(d):
                period_rows.append(e)
            # else: after period_to — ignored for this statement window
        opening_by_ccy[ccy] = opening
        # Status on invoice/correction rows from settlements through period_to.
        # ``status``              — legacy vocabulary, unchanged (pinned).
        # ``presentation_status`` — operator vocabulary from the ONE backend
        #                           authority ``derive_presentation_status``.
        for e in period_rows:
            if e.get("type") in ("invoice", "correction", "normal"):
                inv_id = e.get("wfirma_doc_id") or ""
                inv = invoice_by_id.get(inv_id)
                if inv is not None:
                    paid = paid_against_invoice.get(inv_id, Decimal("0"))
                    rem = remaining_after_payments(inv["brutto"], paid)
                    is_corr = inv.get("type") == "correction"
                    if is_corr:
                        e["status"] = "Issued"
                    elif rem <= 0:
                        e["status"] = "Paid"
                    elif paid > 0:
                        e["status"] = "Partial"
                    else:
                        e["status"] = "Open"
                    e["presentation_status"] = derive_presentation_status(
                        entry_type="invoice",
                        remaining=rem,
                        due_date=e.get("due_date") or "",
                        as_of=statement_date,
                        is_credit_document=bool(
                            is_corr and (inv.get("brutto") or Decimal("0")) < 0
                        ),
                        source_payment_state=inv.get("payment_state") or "",
                        has_explaining_correction=(inv_id in corrected_parent_ids),
                    )
                    parent = str(inv.get("correction_of_id") or "")
                    if parent:
                        pinv = invoice_by_id.get(parent)
                        e["reference"] = (
                            (pinv or {}).get("fullnumber") or parent
                        )
                else:
                    e["status"] = e.get("status") or ""
                    e["presentation_status"] = e.get("presentation_status") or ""
            elif e.get("type") == "payment":
                e["status"] = "Applied"
                linked = str(e.get("linked_invoice") or "")
                e["presentation_status"] = derive_presentation_status(
                    entry_type="payment",
                    is_unmatched=not linked,
                )
                if linked:
                    linv = invoice_by_id.get(linked)
                    e["reference"] = (linv or {}).get("fullnumber") or linked
            e.pop("paymentdate", None)
            e["source"] = "wfirma"
        # Running balance from opening through period movements
        running = opening
        for e in period_rows:
            running += Decimal(e["debit"]) - Decimal(e["credit"])
            e["running_balance"] = _q(running)
        # Prepend B/F row when there is prior activity OR non-zero opening
        display_rows: List[Dict[str, Any]] = []
        if opening != 0 or any(_before_period(e.get("date") or "") for e in rows):
            bf_debit = opening if opening > 0 else Decimal("0")
            bf_credit = (-opening) if opening < 0 else Decimal("0")
            display_rows.append({
                "type": "opening_balance",
                "wfirma_doc_id": "",
                "doc_number": "OPENING BALANCE / B/F",
                "date": period_from or "",
                # A carried-forward balance has no due date of its own.
                "due_date": "",
                "reference": "",
                "currency": ccy,
                "debit": _q(bf_debit),
                "credit": _q(bf_credit),
                "running_balance": _q(opening),
                "status": "B/F",
                "presentation_status": PRESENTATION_STATUS_BF,
                "source": "carried",
                "is_opening_balance": True,
            })
        display_rows.extend(period_rows)
        period_entries_by_ccy[ccy] = display_rows

    entries_by_ccy = period_entries_by_ccy

    # Currencies with only pre-period activity still need a closing view
    for ccy, opening in opening_by_ccy.items():
        if ccy not in entries_by_ccy:
            entries_by_ccy[ccy] = []
        currencies.add(ccy)

    # ── Per-currency totals (period activity + carried balances) ───────
    totals_by_ccy: Dict[str, Dict[str, Any]] = {}
    for ccy in sorted(currencies):
        rows = [e for e in (entries_by_ccy.get(ccy) or [])
                if not e.get("is_opening_balance")]
        opening = opening_by_ccy.get(ccy, Decimal("0"))
        invoiced = Decimal("0")
        credited = Decimal("0")
        received = Decimal("0")
        period_debits = Decimal("0")
        period_credits = Decimal("0")
        fx_adjustments = Decimal("0")  # no FX authority — always zero unless lines exist
        for e in rows:
            d = Decimal(e["debit"])
            c = Decimal(e["credit"])
            period_debits += d
            period_credits += c
            if e["type"] in ("invoice", "correction"):
                invoiced += d
                credited += c
            elif e["type"] == "payment":
                received += c
                received -= d
            elif e["type"] == "fx_adjustment":
                fx_adjustments += d - c
        closing = opening + period_debits - period_credits
        # Invariant check (internal); surface as warning if drift
        expected = opening + invoiced - credited - received + fx_adjustments
        if abs(closing - expected) > Decimal("0.005"):
            warnings.append({
                "event": "statement_closing_invariant_drift",
                "currency": ccy,
                "opening": _q(opening),
                "closing": _q(closing),
                "expected": _q(expected),
            })
        totals_by_ccy[ccy] = {
            "opening_balance": _q(opening),
            "period_debits":   _q(period_debits),
            "period_credits":  _q(period_credits),
            "fx_adjustments":  _q(fx_adjustments),
            "closing_balance": _q(closing),
            "invoiced":    _q(invoiced),
            "credited":    _q(credited),
            "received":    _q(received),
            # Legacy alias: period closing — NOT current portfolio open.
            # UI/PDF must label this "Closing balance", never "Outstanding".
            "outstanding": _q(closing),
            "entry_count": len(rows),
        }

    # ── Aging per currency ────────────────────────────────────────────
    # Aging uses the FULL loaded invoice set (history floor → period to)
    # with settlements through period_to, anchored at statement_date —
    # this is the as-of position view, not the period activity subtotal.
    aging_by_ccy: Dict[str, Dict[str, Any]] = {}
    oldest_overdue_date = ""
    # POSITION accumulators — the as-of economic position, kept strictly
    # apart from the ACTIVITY totals above. Gathered on the SAME walk and
    # the SAME remainings the aging buckets are built from, so the aging
    # block and the position block can never disagree.
    gross_by_ccy: Dict[str, Decimal] = {}
    credit_by_ccy: Dict[str, Decimal] = {}
    overdue_by_ccy: Dict[str, Decimal] = {}
    not_due_by_ccy: Dict[str, Decimal] = {}
    unavailable_by_ccy: Dict[str, Decimal] = {}
    for ccy in sorted(currencies):
        bucket: Dict[str, Decimal] = {b: Decimal("0") for b in _AGING_BUCKETS}
        due_unavailable = Decimal("0")
        gross_open = Decimal("0")
        credit_open = Decimal("0")
        overdue_open = Decimal("0")
        not_due_open = Decimal("0")
        # Walk invoices in this currency only — payments don't age.
        for inv in invoice_facts:
            if (inv["currency"] or "PLN") != ccy:
                continue
            if not inv["date"]:
                continue
            paid = paid_against_invoice.get(inv["id"], Decimal("0"))
            remaining = remaining_after_payments(inv["brutto"], paid)
            if remaining < 0:
                # A credit note / over-settled document. Never aged (same
                # rule as accounting_analytics credit_balance) — but it MUST
                # be surfaced, otherwise the operator sees a large overdue
                # figure with no sign of the credit that offsets it.
                credit_open += -remaining
                continue
            if remaining == 0:
                continue
            gross_open += remaining
            if method == AGING_METHOD_DUE_DATE:
                anchor = (inv.get("paymentdate") or "").strip()
                if not anchor:
                    warnings.append({
                        "event":         "paymentdate_missing",
                        "wfirma_doc_id": inv["id"],
                    })
                    due_unavailable += remaining
                    continue
                days_old = _days_between(statement_date, anchor)
            else:
                days_old = _days_between(statement_date, inv["date"])
                anchor = (inv.get("date") or "").strip()
            b = _bucket_for_days(days_old)
            bucket[b] += remaining
            # Overdue = days_old > 0 (due date strictly before as-of).
            if days_old > 0:
                overdue_open += remaining
                if anchor:
                    if not oldest_overdue_date or anchor < oldest_overdue_date:
                        oldest_overdue_date = anchor
            else:
                not_due_open += remaining
        gross_by_ccy[ccy] = gross_open
        credit_by_ccy[ccy] = credit_open
        overdue_by_ccy[ccy] = overdue_open
        not_due_by_ccy[ccy] = not_due_open
        unavailable_by_ccy[ccy] = due_unavailable
        # ``total`` is the OPEN BALANCE of the block, not the dated
        # subtotal. financial_aging is the authority and it is explicit:
        # "invariant sum(buckets) == open balance", with
        # due_date_unavailable a data-quality lane that is "included in
        # open-balance reconciliation" -- open_total() and
        # buckets_reconcile() both default to include_unavailable=True.
        # The supplier statement already totals that way (it sums
        # AGING_BUCKETS_WITH_UNAVAILABLE); this one summed only the dated
        # buckets, so ONE product carried TWO meanings of "total" and the
        # client aging block did not reconcile to its own gross exposure --
        # measured 9366.00 printed under a gross of 10104.00, on the same
        # facts where the supplier block printed 10104.00. The buckets, the
        # position block and every other figure are untouched; only the
        # subtotal's definition is brought back to the single authority,
        # and it is read from that authority rather than re-summed here.
        block: Dict[str, Any] = {
            "method":  method,
            **{k: _q(v) for k, v in bucket.items()},
        }
        if method == AGING_METHOD_DUE_DATE:
            block["due_date_unavailable"] = _q(due_unavailable)
        block["total"] = _q(_open_total_canonical(block))
        aging_by_ccy[ccy] = block

    # ── POSITION per currency (as-of economic position) ────────────────
    # ACTIVITY (totals_per_currency) answers "what moved in the period".
    # POSITION answers "what is owed as of the as-of date". They are two
    # different questions and must never be rendered as one number.
    #
    # The identity is the canonical one already used by the receivables /
    # payables portfolio in accounting_analytics (``credit_balance`` is the
    # sum of negative remainings, never aged; net = gross − credits):
    #
    #     GROSS EXPOSURE − CUSTOMER CREDITS = NET POSITION
    #
    # ``aging_basis`` is emitted so the renderer is obliged to label the
    # buckets honestly: they are GROSS, before credits. Showing a net of
    # zero beside a gross overdue figure without the offsetting credit in
    # the same block is the exact defect this block exists to prevent.
    position_by_ccy: Dict[str, Dict[str, Any]] = {}
    for ccy in sorted(currencies):
        gross_open = gross_by_ccy.get(ccy, Decimal("0"))
        credit_open = credit_by_ccy.get(ccy, Decimal("0"))
        position_by_ccy[ccy] = {
            "gross_exposure":       _q(gross_open),
            "customer_credits":     _q(credit_open),
            "credit_balance":       _q(credit_open),
            "net_position":         _q(gross_open - credit_open),
            "overdue":              _q(overdue_by_ccy.get(ccy, Decimal("0"))),
            "not_due":              _q(not_due_by_ccy.get(ccy, Decimal("0"))),
            "due_date_unavailable": _q(unavailable_by_ccy.get(ccy, Decimal("0"))),
            "aging_basis":          AGING_BASIS_GROSS,
            "presentation_state":   presentation_state(gross_open, credit_open),
        }

    cmeta = contractor_meta or {}
    # No ``source`` key here on purpose. This function is a formula over a
    # fact set; it cannot know WHICH fact universe produced that set, and a
    # hardcoded "wfirma" was a false provenance claim from the moment the
    # routes started defaulting to source=local -- the PDF header printed
    # "Source wfirma" over numbers read from the local projection. The route
    # that performed the read stamps ``source`` / ``freshness`` /
    # ``reconciliation_status`` on the body (routes_ledgers), exactly as the
    # supplier producer already relies on. A reader with no stamp sees an
    # honest em dash, never a claim nobody verified.
    return {
        "contractor": {
            "wfirma_contractor_id": str(
                cmeta.get("wfirma_contractor_id") or ""
            ),
            "name":     str(cmeta.get("name")    or ""),
            "country":  str(cmeta.get("country") or ""),
            "vat_id":   str(cmeta.get("vat_id")  or ""),
            "street":   str(cmeta.get("street")  or ""),
            "city":     str(cmeta.get("city")    or ""),
            "postal_code": str(cmeta.get("postal_code") or ""),
            "email":    str(cmeta.get("email")   or ""),
            "phone":    str(cmeta.get("phone")   or ""),
        },
        "generated_at":   statement_date,
        "period":         {"from": str(df or ""), "to": str(dt or "")},
        "period_start":   str(df or ""),
        "period_end":     str(dt or ""),
        "position_as_of": statement_date,
        "as_of":          statement_date,
        "statement_model": "opening_period_closing",
        "currencies":     sorted(currencies),
        "entries_per_currency":          entries_by_ccy,
        "totals_per_currency":           totals_by_ccy,
        "position_per_currency":         position_by_ccy,
        "aging_per_currency":            aging_by_ccy,
        "unmatched_payments_per_currency": unmatched_payments_by_ccy,
        "presentation_state": presentation_state_from_maps(
            gross_by_ccy, credit_by_ccy
        ),
        "aging_basis": AGING_BASIS_GROSS,
        "oldest_overdue_date": oldest_overdue_date or None,
        "warnings":       warnings,
        "aging_method":   method,
    }


def aggregate_statement(
    contractor_meta: Dict[str, Any],
    invoice_nodes:   List[ET.Element],
    payment_nodes:   List[ET.Element],
    statement_date:  str,
    period:          tuple,
    *,
    aging_method: str = AGING_METHOD_DUE_DATE,
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
    invoice_facts = [_parse_invoice_fact(n) for n in (invoice_nodes or [])]
    payment_facts = [_parse_payment_fact(n) for n in (payment_nodes or [])]
    return aggregate_statement_from_facts(
        contractor_meta,
        invoice_facts,
        payment_facts,
        statement_date,
        period,
        aging_method=aging_method,
    )


def build_statement_index_by_contractor(
    invoice_facts: List[Dict[str, Any]],
    payment_facts: List[Dict[str, Any]],
    *,
    statement_date: str,
    period: tuple,
    aging_method: str = AGING_METHOD_DUE_DATE,
) -> Dict[str, Dict[str, Any]]:
    """One bulk AR fact universe → per-contractor statement dicts.

    Payments are scoped by ``contractor_id`` exactly as
    ``payments/find`` with contractor filter (no silent inheritance from
    linked invoice). Used by Client Balance roster so
    ``per_customer_wfirma_calls=0``.
    """
    inv_by_cid: Dict[str, List[Dict[str, Any]]] = {}
    for inv in invoice_facts or []:
        cid = (inv.get("contractor_id") or "").strip()
        if not cid:
            continue
        inv_by_cid.setdefault(cid, []).append(inv)

    pay_by_cid: Dict[str, List[Dict[str, Any]]] = {}
    for pay in payment_facts or []:
        cid = (pay.get("contractor_id") or "").strip()
        if not cid:
            continue
        pay_by_cid.setdefault(cid, []).append(pay)

    out: Dict[str, Dict[str, Any]] = {}
    for cid in set(inv_by_cid) | set(pay_by_cid):
        out[cid] = aggregate_statement_from_facts(
            {"wfirma_contractor_id": cid},
            inv_by_cid.get(cid, []),
            pay_by_cid.get(cid, []),
            statement_date,
            period,
            aging_method=aging_method,
        )
    return out


__all__ = [
    "LEDGER_ENTRY_FIELDS",
    "FORBIDDEN_ENTRY_FIELDS",
    "AGING_METHOD_DUE_DATE",
    "AGING_METHOD_INVOICE_AGE",
    "aggregate_invoice_ledger",
    # Phase 10B
    "aggregate_statement",
    "aggregate_statement_from_facts",
    "build_statement_index_by_contractor",
    "remaining_after_payments",
    "match_payments_to_invoices",
    "match_payments_to_expenses",
    "aggregate_supplier_statement",
    "_normalize_doc_link_id",
    "_is_iso_currency_code",
    "_parse_payment_fact",
    "_parse_invoice_fact",
    "_parse_expense_fact",
]
