"""
customer_commercial_profile.py — auto-generate commercial profile from history.

Source of truth: INVOICES ONLY (sales-side, export VAT). Proformas excluded.

Why invoices only:
  - Proformas are draft / test / cancelled / negotiated — noisy by nature
  - Invoices represent committed commercial reality
  - Invoices have already passed accounting validation

Pipeline:
    fetch_export_invoices(contractor_id)        I/O — wFirma read
        ↓
    InvoiceRecord[]                             pure data
        ↓
    build_profile_from_invoices(records)        pure function
        ↓
    CustomerCommercialProfile                   structured output

Confidence states (LOCKED — match the rules from manual extraction):
    EMPTY              0 invoices
    SINGLE_DOC         exactly 1 invoice (insufficient for pattern)
    STALE_LOW          ≥2 invoices but most recent > 12 months ago
    CONSISTENT_RECENT  ≥2 recent invoices and all stable fields agree
    VARYING            ≥2 recent invoices but stable fields disagree

Freight detection:
    Look at last_n=5 invoice freight values.
    If all equal → fixed (use that value).
    Else → variable (operator must supply per shipment).

Insurance detection:
    For each invoice with subtotal>0, compute ratio = insurance / subtotal.
    If ≥80% of ratios cluster at 0.0035 ±0.0002 → mode='formula'.
    Else → mode='fixed' (min = smallest observed insurance).
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Callable, Dict, List, Optional, Tuple


# ── Constants (locked) ────────────────────────────────────────────────────────

# Service good_ids for line classification — same as used elsewhere.
FREIGHT_SERVICE_ID    = "13002743"
INSURANCE_SERVICE_ID  = "13102217"
FREIGHT_KEYWORDS      = ("fedex", "freight", "fracht", "courier", "dhl",
                          "transport", "shipping", "shipment", "postage")
INSURANCE_KEYWORDS    = ("insurance", "ubezpieczenie")

# Export VAT codes — only invoices with one of these are kept.
EXPORT_VAT_CODES      = frozenset({"228", "229"})

# Configurable thresholds.
RECENT_WINDOW_MONTHS  = 12
FREIGHT_RECENT_N      = 5
INSURANCE_RATE        = Decimal("0.0035")
INSURANCE_RATE_TOL    = Decimal("0.0002")
INSURANCE_FORMULA_FRACTION_THRESHOLD = Decimal("0.80")   # ≥80% must hit the formula


# ── Confidence states ────────────────────────────────────────────────────────

CONF_EMPTY              = "EMPTY"
CONF_SINGLE_DOC         = "SINGLE_DOC"
CONF_STALE_LOW          = "STALE_LOW"
CONF_CONSISTENT_RECENT  = "CONSISTENT_RECENT"
CONF_VARYING            = "VARYING"


# ── Data types ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class InvoiceRecord:
    """Pure data — one historical sales invoice."""
    invoice_id:               str
    fullnumber:               str
    date:                     str          # ISO YYYY-MM-DD
    currency:                 str
    language_id:              str
    series_id:                str
    vat_codes:                Tuple[str, ...]
    product_subtotal:         Decimal
    freight_amount:           Optional[Decimal]
    insurance_amount:         Optional[Decimal]
    description:              str
    contractor_receiver_id:   str


@dataclass(frozen=True)
class FreightProfile:
    mode:    str               # "fixed" | "variable" | "no_data"
    value:   Optional[Decimal] # the recommended freight when mode=fixed
    history: Tuple[Decimal, ...]


@dataclass(frozen=True)
class InsuranceProfile:
    mode:               str            # "formula" | "fixed" | "no_data"
    rate:               Decimal        # the formula rate (always 0.0035)
    min:                Optional[Decimal]
    formula_fraction:   Decimal        # share of invoices where formula applied


@dataclass(frozen=True)
class CustomerCommercialProfile:
    contractor_id:           str
    invoice_count:           int
    most_recent_date:        Optional[str]
    earliest_date:           Optional[str]

    # Stable fields (high confidence when consistent)
    preferred_currency:      Optional[str]
    preferred_language_id:   Optional[str]
    series_by_type:          Dict[str, str] = field(default_factory=dict)
    vat_mode:                Optional[int] = None
    ship_to_mode:            str = "none"     # "none" | "separate_contractor"

    # Semi-stable fields
    freight:                 Optional[FreightProfile]   = None
    insurance:               Optional[InsuranceProfile] = None
    description_template:    str = ""

    # Confidence
    confidence_state:        str = CONF_EMPTY
    confidence_notes:        Tuple[str, ...] = ()


# ── I/O — fetch invoices for a customer ──────────────────────────────────────

def fetch_export_invoices(contractor_id: str,
                          *,
                          months_back: Optional[int] = None,
                          limit:       int = 100) -> List[InvoiceRecord]:
    """Live wFirma read. Returns ONLY type=normal invoices for this contractor
    that carry export VAT (228 WDT or 229 EXP). Proformas excluded.

    months_back=None → no date filter (return everything in account).
    months_back=N    → only invoices with date >= today - N months.
    """
    from app.services import wfirma_client as wfc

    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<api>
  <invoices>
    <parameters>
      <conditions>
        <condition><field>type</field><operator>eq</operator><value>normal</value></condition>
        <condition><field>contractor_id</field><operator>eq</operator><value>{contractor_id}</value></condition>
      </conditions>
      <order><asc>0</asc><field>id</field></order>
      <page><start>0</start><limit>{int(limit)}</limit></page>
    </parameters>
  </invoices>
</api>"""
    http_status, response = wfc._http_request("GET", "invoices", "find", body)
    if http_status >= 400:
        raise ConnectionError(f"invoices/find HTTP {http_status}")

    try:
        root = ET.fromstring(response)
    except ET.ParseError:
        return []

    cutoff = None
    if months_back is not None:
        # months are coarse; compute cutoff date
        d = date.today()
        # subtract roughly months_back × 30 days for simplicity
        cutoff = d - timedelta(days=months_back * 31)

    out: List[InvoiceRecord] = []
    for inv in root.findall("invoices/invoice"):
        rec = _parse_invoice(inv)
        if rec is None:
            continue
        # Export VAT filter
        if not (set(rec.vat_codes) & EXPORT_VAT_CODES):
            continue
        # Date filter
        if cutoff is not None:
            try:
                inv_date = date.fromisoformat(rec.date)
            except (ValueError, TypeError):
                continue
            if inv_date < cutoff:
                continue
        out.append(rec)

    # Sort newest-first regardless of what wFirma returned (the <order><asc>0</asc>
    # parameter does NOT reliably descend — confirmed live 2026-05-03).
    def _key(r: InvoiceRecord):
        try:
            return date.fromisoformat(r.date)
        except (ValueError, TypeError):
            return date(1, 1, 1)
    out.sort(key=_key, reverse=True)
    return out


def _classify_line(name: str, good_id: str) -> str:
    n = (name or "").lower()
    if any(k in n for k in INSURANCE_KEYWORDS) or good_id == INSURANCE_SERVICE_ID:
        return "insurance"
    if any(k in n for k in FREIGHT_KEYWORDS) or good_id == FREIGHT_SERVICE_ID:
        return "freight"
    return "product"


def _parse_invoice(inv: ET.Element) -> Optional[InvoiceRecord]:
    invid = inv.findtext("id") or ""
    if not invid:
        return None

    contents = inv.find("invoicecontents")
    if contents is None:
        return None

    product_subtotal = Decimal("0")
    freight = None
    insurance = None
    vat_codes_set = set()
    for c in contents.findall("invoicecontent"):
        name = c.findtext("name") or ""
        gid_el = c.find("good/id")
        gid = gid_el.text if gid_el is not None and gid_el.text else ""
        try:
            qty   = Decimal(c.findtext("unit_count") or "0")
            price = Decimal(c.findtext("price")      or "0")
        except Exception:
            qty, price = Decimal("0"), Decimal("0")
        vc_el = c.find("vat_code/id")
        vc = vc_el.text if vc_el is not None and vc_el.text else ""
        if vc:
            vat_codes_set.add(vc)
        kind = _classify_line(name, gid)
        if kind == "product":
            product_subtotal += qty * price
        elif kind == "freight" and freight is None:
            freight = price
        elif kind == "insurance" and insurance is None:
            insurance = price

    lang = inv.find("translation_language/id")
    series = inv.find("series/id")
    rcv   = inv.find("contractor_receiver/id")
    return InvoiceRecord(
        invoice_id              = invid,
        fullnumber              = inv.findtext("fullnumber") or "",
        date                    = inv.findtext("date") or "",
        currency                = inv.findtext("currency") or "",
        language_id             = lang.text if lang is not None and lang.text else "",
        series_id               = series.text if series is not None and series.text else "",
        vat_codes               = tuple(sorted(vat_codes_set)),
        product_subtotal        = product_subtotal.quantize(Decimal("0.01")),
        freight_amount          = freight,
        insurance_amount        = insurance,
        description             = (inv.findtext("description") or "").strip(),
        contractor_receiver_id  = rcv.text if rcv is not None and rcv.text else "0",
    )


# ── Pure profile builder ─────────────────────────────────────────────────────

def _is_recent(iso_date: Optional[str], months: int = RECENT_WINDOW_MONTHS) -> bool:
    if not iso_date:
        return False
    try:
        d = date.fromisoformat(iso_date)
    except (ValueError, TypeError):
        return False
    return (date.today() - d).days <= months * 31


def _detect_freight(invoices: List[InvoiceRecord]) -> Optional[FreightProfile]:
    """Examine the last FREIGHT_RECENT_N invoices' freight values."""
    with_freight = [i for i in invoices if i.freight_amount is not None]
    if not with_freight:
        return FreightProfile(mode="no_data", value=None, history=tuple())
    history = tuple(i.freight_amount for i in with_freight[:FREIGHT_RECENT_N])
    if all(h == history[0] for h in history):
        return FreightProfile(mode="fixed", value=history[0], history=history)
    return FreightProfile(mode="variable", value=None, history=history)


def _detect_insurance(invoices: List[InvoiceRecord]) -> Optional[InsuranceProfile]:
    """If most invoices' insurance / subtotal ≈ 0.0035, mode=formula. Else fixed."""
    relevant = [i for i in invoices
                if i.insurance_amount is not None and i.product_subtotal > 0]
    if not relevant:
        return InsuranceProfile(mode="no_data", rate=INSURANCE_RATE,
                                min=None, formula_fraction=Decimal("0"))
    formula_hits = 0
    for i in relevant:
        ratio = (i.insurance_amount / i.product_subtotal).quantize(Decimal("0.000001"))
        if abs(ratio - INSURANCE_RATE) <= INSURANCE_RATE_TOL:
            formula_hits += 1
    fraction = (Decimal(formula_hits) / Decimal(len(relevant))).quantize(Decimal("0.001"))
    min_ins = min(i.insurance_amount for i in relevant)
    if fraction >= INSURANCE_FORMULA_FRACTION_THRESHOLD:
        return InsuranceProfile(mode="formula", rate=INSURANCE_RATE,
                                min=min_ins, formula_fraction=fraction)
    return InsuranceProfile(mode="fixed", rate=INSURANCE_RATE,
                            min=min_ins, formula_fraction=fraction)


def _detect_ship_to_mode(invoices: List[InvoiceRecord]) -> str:
    """If any invoice has contractor_receiver_id != 0 → separate_contractor.
    Else → none. (Alternate-address shape is invisible at the invoice level —
    that lives on the contractor record, not the invoice.)"""
    for i in invoices:
        if i.contractor_receiver_id and i.contractor_receiver_id != "0":
            return "separate_contractor"
    return "none"


def _detect_vat_mode(invoices: List[InvoiceRecord]) -> Optional[int]:
    """If all line VAT codes across all invoices are 228 → 228.
    If all are 229 → 229. Otherwise None (operator must decide per doc)."""
    all_vats = set()
    for i in invoices:
        for v in i.vat_codes:
            all_vats.add(v)
    if all_vats == {"228"}: return 228
    if all_vats == {"229"}: return 229
    return None


def _series_by_type(invoices: List[InvoiceRecord]) -> Dict[str, str]:
    """We only see invoice docs in this profile builder, so the only series we
    can observe is the invoice series. Returned as {"invoice": series_id}."""
    if not invoices:
        return {}
    invoice_series = {i.series_id for i in invoices if i.series_id}
    if len(invoice_series) == 1:
        return {"invoice": next(iter(invoice_series))}
    return {}


def build_profile_from_invoices(contractor_id:    str,
                                 invoices:        List[InvoiceRecord]) -> CustomerCommercialProfile:
    """Pure: derive a profile from a list of export invoices.

    Invoices should already be (a) sales-side, (b) export VAT only, (c) sorted
    newest-first (this function does not enforce — caller's responsibility).
    """
    notes: List[str] = []

    if not invoices:
        return CustomerCommercialProfile(
            contractor_id     = contractor_id,
            invoice_count     = 0,
            most_recent_date  = None,
            earliest_date     = None,
            preferred_currency      = None,
            preferred_language_id   = None,
            confidence_state  = CONF_EMPTY,
            confidence_notes  = ("no invoices found",),
        )

    most_recent = invoices[0].date
    earliest    = invoices[-1].date
    recent      = _is_recent(most_recent)

    # Aggregate stable fields
    currencies = {i.currency for i in invoices if i.currency}
    languages  = {i.language_id for i in invoices if i.language_id}

    pref_currency = next(iter(currencies)) if len(currencies) == 1 else None
    pref_language = next(iter(languages))  if len(languages) == 1 else None

    vat_mode    = _detect_vat_mode(invoices)
    series_map  = _series_by_type(invoices)
    ship_mode   = _detect_ship_to_mode(invoices)
    freight     = _detect_freight(invoices)
    insurance   = _detect_insurance(invoices)
    desc_template = ""
    for i in invoices:
        if i.description:
            desc_template = i.description
            break

    # Confidence state
    if len(invoices) == 1:
        state = CONF_SINGLE_DOC
        notes.append("only 1 invoice — insufficient for stable pattern")
    elif not recent:
        state = CONF_STALE_LOW
        notes.append(f"most recent invoice is {most_recent} — older than {RECENT_WINDOW_MONTHS} months")
    else:
        # ≥2 recent invoices
        all_consistent = (
            pref_currency is not None
            and pref_language is not None
            and vat_mode is not None
        )
        state = CONF_CONSISTENT_RECENT if all_consistent else CONF_VARYING
        if not all_consistent:
            if pref_currency is None: notes.append(f"currency varies: {sorted(currencies)}")
            if pref_language is None: notes.append(f"language varies: {sorted(languages)}")
            if vat_mode      is None: notes.append("vat codes vary across invoices")

    # Field-specific warnings (always added regardless of overall state)
    if freight and freight.mode == "variable":
        notes.append(f"freight varies: {sorted({float(v) for v in freight.history})}")
    if insurance and insurance.mode == "fixed":
        notes.append(f"insurance pattern not formula (only {insurance.formula_fraction:.0%} of invoices match 0.35%)")
    if ship_mode == "separate_contractor":
        notes.append("at least one invoice used contractor_receiver — verify ship-to per shipment")

    return CustomerCommercialProfile(
        contractor_id        = contractor_id,
        invoice_count        = len(invoices),
        most_recent_date     = most_recent,
        earliest_date        = earliest,
        preferred_currency   = pref_currency,
        preferred_language_id= pref_language,
        series_by_type       = series_map,
        vat_mode             = vat_mode,
        ship_to_mode         = ship_mode,
        freight              = freight,
        insurance            = insurance,
        description_template = desc_template,
        confidence_state     = state,
        confidence_notes     = tuple(notes),
    )


# ── Top-level orchestrator ───────────────────────────────────────────────────

def generate_profile(contractor_id: str,
                     *,
                     months_back: Optional[int] = None,
                     fetcher:     Optional[Callable] = None) -> CustomerCommercialProfile:
    """Live: fetch invoices for the contractor and derive the profile."""
    fetch = fetcher or (lambda cid, mb: fetch_export_invoices(cid, months_back=mb))
    invoices = fetch(contractor_id, months_back)
    return build_profile_from_invoices(contractor_id, invoices)


__all__ = [
    "CONF_CONSISTENT_RECENT", "CONF_EMPTY", "CONF_SINGLE_DOC",
    "CONF_STALE_LOW", "CONF_VARYING",
    "EXPORT_VAT_CODES", "FREIGHT_SERVICE_ID", "INSURANCE_SERVICE_ID",
    "INSURANCE_RATE", "RECENT_WINDOW_MONTHS",
    "CustomerCommercialProfile", "FreightProfile", "InsuranceProfile",
    "InvoiceRecord",
    "build_profile_from_invoices", "fetch_export_invoices", "generate_profile",
]
