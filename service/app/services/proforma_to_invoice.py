"""
proforma_to_invoice.py — pure builder that turns an existing wFirma proforma
into a final-invoice request body.

Why this exists
    wFirma exposes NO native proforma → invoice conversion endpoint (probe
    results 2026-05-03). Every action we tested — copy, convert, transform,
    settle, finalize, issue, markpaid, markaspaid, pay, close, book, realize,
    clone, duplicate, fromproforma — returned ACTION NOT FOUND. The /add
    endpoint silently ignores <proforma>, <based_on>, <from_proforma>
    wrapper tags.

    So conversion = read the proforma, project its fields, emit a fresh
    invoices/add body with <type>normal</type>. This module does that
    projection. Pure function. No HTTP. No DB.

Input
    The full <invoice>...</invoice> XML element from a successful
    invoices/find for the source proforma.

Output
    A complete <api><invoices><invoice>... body ready to POST to invoices/add.

Locked rules
    1. <type>proforma</type>  →  <type>normal</type>
    2. The same contractor (by id) is referenced.
    3. All <invoicecontent> rows are copied verbatim (good id, name, unit,
       unit_count, price, vat_code id) — including freight + insurance lines.
    4. Currency, FX, payment method, payment date are copied unchanged.
    5. Series id is operator-supplied (final invoice usually uses a different
       series than proforma — e.g. 15827921 WDT vs 15827088 proforma).
    6. <date> on the final invoice is operator-supplied (today by default);
       the original proforma date is preserved in <description>.
    7. <description> ALWAYS includes a back-reference:
            "Final invoice issued based on proforma <fullnumber> (id=<id>)"
       prepended to whatever description the operator passes (or to the
       original proforma description if none is supplied).
    8. translation_language and company_account are copied if present.
    9. ship-to (contractor_receiver) is copied if present.

What this module does NOT do
    - It does NOT call wFirma.
    - It does NOT touch the link DB.
    - It does NOT decide whether stock is available.
    - It does NOT recompute totals — wFirma recomputes from line items.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import List, Optional, Tuple


# ── Public types ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ProformaSnapshot:
    """Subset of a proforma's XML that we need to build the final invoice.

    Every field is taken AS-IS from the proforma — no recomputation.
    """
    proforma_id:             str
    proforma_number:         str           # e.g. "PROF 90/2026"
    type:                    str           # MUST be 'proforma'
    contractor_id:           str
    currency:                str
    price_currency_exchange: Optional[str]  # six-decimal string or None
    paymentmethod:           str
    paymentdate:             str           # ISO date
    date:                    str           # original proforma date
    description:             str
    series_id:               Optional[str]
    company_account_id:      Optional[str]
    translation_language_id: Optional[str]
    contractor_receiver_id:  Optional[str]
    total:                   Decimal       # for plan/safety check; not sent
    netto:                   Decimal
    contents:                List["LineItem"] = field(default_factory=list)


@dataclass(frozen=True)
class LineItem:
    """One <invoicecontent> row, taken verbatim from the proforma."""
    name:        str
    good_id:     str
    unit:        str
    unit_count:  str
    price:       str
    vat_code_id: str


@dataclass(frozen=True)
class FinalInvoicePlan:
    """What we will send. Keep alongside ProformaSnapshot for the operator
    plan dump and for the link DB (source_total, currency)."""
    type:                    str           # always 'normal'
    contractor_id:           str
    currency:                str
    price_currency_exchange: Optional[str]
    paymentmethod:           str
    paymentdate:             str           # may be operator-overridden
    date:                    str           # operator-supplied issue date
    description:             str           # back-reference + operator description
    series_id:               str           # final invoice series (operator)
    company_account_id:      Optional[str]
    translation_language_id: Optional[str]
    contractor_receiver_id:  Optional[str]
    contents:                List[LineItem]
    # informational, not sent in XML
    source_proforma_id:      str
    source_proforma_number:  str
    expected_total:          Decimal


class ProformaParseError(ValueError):
    """Raised when the proforma XML is missing fields we require."""


class NotAProforma(ValueError):
    """Raised when the input <invoice> element is not <type>proforma</type>."""


# ── XML parsing ──────────────────────────────────────────────────────────────

def _txt(el: Optional[ET.Element], path: str, default: str = "") -> str:
    if el is None:
        return default
    found = el.find(path)
    if found is None or found.text is None:
        return default
    return found.text.strip()


def parse_proforma_xml(invoice_xml: str) -> ProformaSnapshot:
    """Parse a single <invoice> element from a wFirma response into a
    ProformaSnapshot. Accepts either a bare <invoice>...</invoice> or the
    full <api><invoices><invoice>... wrapper.

    Raises:
        ProformaParseError if required fields are missing.
        NotAProforma if <type> is not 'proforma'.
    """
    if not invoice_xml or "<invoice>" not in invoice_xml:
        raise ProformaParseError("input is not a wFirma invoice XML")

    # Strip wrapper if present so we can parse a single element.
    m = re.search(r"<invoice>(.*)</invoice>", invoice_xml, flags=re.DOTALL)
    if not m:
        raise ProformaParseError("could not isolate <invoice>...</invoice> block")
    inner = "<invoice>" + m.group(1) + "</invoice>"

    try:
        root = ET.fromstring(inner)
    except ET.ParseError as exc:
        raise ProformaParseError(f"invoice XML is not parseable: {exc}") from exc

    pid = _txt(root, "id")
    if not pid:
        raise ProformaParseError("missing <id>")
    pnum = _txt(root, "fullnumber")
    if not pnum:
        raise ProformaParseError("missing <fullnumber>")
    ptype = _txt(root, "type")
    if not ptype:
        raise ProformaParseError("missing <type>")
    if ptype != "proforma":
        raise NotAProforma(
            f"<type> is {ptype!r}, expected 'proforma' — refusing to convert"
        )

    contractor_el = root.find("contractor")
    contractor_id = _txt(contractor_el, "id")
    if not contractor_id:
        raise ProformaParseError("missing <contractor><id>")

    currency = _txt(root, "currency")
    if not currency:
        raise ProformaParseError("missing <currency>")

    paymentmethod = _txt(root, "paymentmethod")
    if not paymentmethod:
        raise ProformaParseError("missing <paymentmethod>")
    paymentdate = _txt(root, "paymentdate")
    if not paymentdate:
        raise ProformaParseError("missing <paymentdate>")
    pdate = _txt(root, "date")
    if not pdate:
        raise ProformaParseError("missing <date>")

    fx = _txt(root, "price_currency_exchange") or None
    # wFirma uses "0" as a sentinel for "no value" on id-style fields (observed
    # on company_account, contractor_receiver, series). Treat both empty and
    # literal "0" as None so we don't emit invalid <id>0</id> blocks downstream.
    def _id_or_none(value: str) -> Optional[str]:
        v = (value or "").strip()
        return None if not v or v == "0" else v
    series_id = _id_or_none(_txt(root.find("series"), "id"))
    ca_id     = _id_or_none(_txt(root.find("company_account"), "id"))
    lang_id   = _id_or_none(_txt(root.find("translation_language"), "id"))
    rcv_id    = _id_or_none(_txt(root.find("contractor_receiver"), "id"))

    total_str = _txt(root, "total") or "0"
    netto_str = _txt(root, "netto") or "0"
    try:
        total = Decimal(total_str)
        netto = Decimal(netto_str)
    except Exception as exc:  # noqa: BLE001
        raise ProformaParseError(f"non-numeric total/netto: {exc}") from exc

    description = _txt(root, "description") or ""

    # Line items
    contents_el = root.find("invoicecontents")
    contents: List[LineItem] = []
    if contents_el is not None:
        for ic in contents_el.findall("invoicecontent"):
            good_id = _txt(ic.find("good"), "id")
            vat_id = _txt(ic.find("vat_code"), "id")
            name = _txt(ic, "name")
            unit = _txt(ic, "unit") or "szt."
            unit_count = _txt(ic, "unit_count") or "1.0000"
            price = _txt(ic, "price")
            if not good_id:
                raise ProformaParseError(
                    f"line {len(contents)+1}: missing <good><id>"
                )
            if not vat_id:
                raise ProformaParseError(
                    f"line {len(contents)+1}: missing <vat_code><id>"
                )
            if not price:
                raise ProformaParseError(
                    f"line {len(contents)+1}: missing <price>"
                )
            contents.append(LineItem(
                name=name, good_id=good_id, unit=unit,
                unit_count=unit_count, price=price, vat_code_id=vat_id,
            ))
    if not contents:
        raise ProformaParseError("proforma has no <invoicecontent> rows")

    return ProformaSnapshot(
        proforma_id             = pid,
        proforma_number         = pnum,
        type                    = ptype,
        contractor_id           = contractor_id,
        currency                = currency,
        price_currency_exchange = fx,
        paymentmethod           = paymentmethod,
        paymentdate             = paymentdate,
        date                    = pdate,
        description             = description,
        series_id               = series_id,
        company_account_id      = ca_id,
        translation_language_id = lang_id,
        contractor_receiver_id  = rcv_id,
        total                   = total,
        netto                   = netto,
        contents                = contents,
    )


# ── Plan builder ──────────────────────────────────────────────────────────────

BACK_REFERENCE_TEMPLATE = "Final invoice issued based on proforma {pnum} (id={pid})."


def build_final_invoice_plan(
    snap: ProformaSnapshot,
    *,
    final_series_id:    str,
    invoice_date:       Optional[date] = None,
    paymentdate:        Optional[str]  = None,
    operator_description: Optional[str] = None,
) -> FinalInvoicePlan:
    """Project a parsed proforma snapshot into a FinalInvoicePlan.

    Args:
        final_series_id:      wFirma series id for the final invoice.
                              When empty or omitted, no ``<series>`` element
                              is emitted and wFirma applies its contractor
                              default series. (ADR-027 D6: step 3 = omit.)
        invoice_date:         The issue date of the final invoice. Defaults
                              to today (UTC date).
        paymentdate:          Override payment date. Defaults to the proforma's
                              own paymentdate (so the operator may explicitly
                              keep or shift the due date).
        operator_description: Optional extra text appended after the back-
                              reference. The back-reference is ALWAYS prepended
                              regardless of this value.
    """
    # ADR-027 D6 step 3: empty final_series_id is valid — <series> will be
    # omitted and wFirma will use its own contractor default.  Do NOT raise.

    issue_date = invoice_date or date.today()

    back_ref = BACK_REFERENCE_TEMPLATE.format(
        pnum=snap.proforma_number, pid=snap.proforma_id,
    )
    if operator_description and operator_description.strip():
        description = f"{back_ref} {operator_description.strip()}"
    elif snap.description:
        description = f"{back_ref} {snap.description}"
    else:
        description = back_ref

    return FinalInvoicePlan(
        type                    = "normal",
        contractor_id           = snap.contractor_id,
        currency                = snap.currency,
        price_currency_exchange = snap.price_currency_exchange,
        paymentmethod           = snap.paymentmethod,
        paymentdate             = paymentdate or snap.paymentdate,
        date                    = issue_date.isoformat(),
        description             = description,
        series_id               = (str(final_series_id).strip() if final_series_id else ""),
        company_account_id      = snap.company_account_id,
        translation_language_id = snap.translation_language_id,
        contractor_receiver_id  = snap.contractor_receiver_id,
        contents                = list(snap.contents),
        source_proforma_id      = snap.proforma_id,
        source_proforma_number  = snap.proforma_number,
        expected_total          = snap.total,
    )


# ── Safety: did the line set change? ─────────────────────────────────────────

def lines_match(a: List[LineItem], b: List[LineItem]) -> Tuple[bool, List[str]]:
    """Compare two line-item lists for exactness. Returns (ok, diffs)."""
    diffs: List[str] = []
    if len(a) != len(b):
        diffs.append(f"line count differs: {len(a)} vs {len(b)}")
    for i, (la, lb) in enumerate(zip(a, b)):
        for f in ("good_id", "unit_count", "price", "vat_code_id"):
            va, vb = getattr(la, f), getattr(lb, f)
            if str(va) != str(vb):
                diffs.append(f"line {i+1} {f}: {va!r} vs {vb!r}")
    return (len(diffs) == 0), diffs


# ── XML emission ──────────────────────────────────────────────────────────────

def _esc(value) -> str:
    s = "" if value is None else str(value)
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;")
             .replace("'", "&apos;"))


def _line_xml(line: LineItem) -> str:
    return (
        "        <invoicecontent>\n"
        f"          <name>{_esc(line.name)}</name>\n"
        f"          <good><id>{_esc(line.good_id)}</id></good>\n"
        f"          <unit>{_esc(line.unit)}</unit>\n"
        f"          <unit_count>{_esc(line.unit_count)}</unit_count>\n"
        f"          <price>{_esc(line.price)}</price>\n"
        f"          <vat_code><id>{_esc(line.vat_code_id)}</id></vat_code>\n"
        "        </invoicecontent>"
    )


def build_final_invoice_xml(plan: FinalInvoicePlan) -> str:
    """Emit the <api><invoices><invoice> body for invoices/add. Pure string.

    ADR-027 D6: when ``plan.series_id`` is empty, the ``<series>`` element is
    omitted entirely so wFirma uses its own contractor-level default series.
    """
    if plan.type != "normal":
        raise ValueError(f"plan.type must be 'normal', got {plan.type!r}")
    if not plan.contents:
        raise ValueError("plan has no line items")
    # series_id empty is valid (step 3: omit; wFirma contractor default applies)

    fx_block = (
        f"      <price_currency_exchange>{_esc(plan.price_currency_exchange)}</price_currency_exchange>\n"
        if plan.price_currency_exchange else ""
    )
    ca_block = (
        f"      <company_account><id>{_esc(plan.company_account_id)}</id></company_account>\n"
        if plan.company_account_id else ""
    )
    lang_block = (
        f"      <translation_language><id>{_esc(plan.translation_language_id)}</id></translation_language>\n"
        if plan.translation_language_id else ""
    )
    rcv_block = (
        f"      <contractor_receiver><id>{_esc(plan.contractor_receiver_id)}</id></contractor_receiver>\n"
        if plan.contractor_receiver_id else ""
    )
    # ADR-027 D6 step 3: omit <series> when no series_id resolved.
    # wFirma applies its own contractor-level default series in that case.
    _sid = (plan.series_id or "").strip()
    series_block = (
        f"      <series><id>{_esc(_sid)}</id></series>\n"
        if _sid and _sid != "0" else ""
    )

    lines_xml = "\n".join(_line_xml(l) for l in plan.contents)

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<api>\n"
        "  <invoices>\n"
        "    <invoice>\n"
        f"      <type>{_esc(plan.type)}</type>\n"
        f"      <date>{_esc(plan.date)}</date>\n"
        f"      <paymentdate>{_esc(plan.paymentdate)}</paymentdate>\n"
        f"      <currency>{_esc(plan.currency)}</currency>\n"
        f"{fx_block}"
        "      <vat_payer>1</vat_payer>\n"
        "      <price_type>netto</price_type>\n"
        f"      <paymentmethod>{_esc(plan.paymentmethod)}</paymentmethod>\n"
        f"      <description>{_esc(plan.description)}</description>\n"
        f"      <contractor><id>{_esc(plan.contractor_id)}</id></contractor>\n"
        f"{rcv_block}"
        f"{series_block}"
        f"{ca_block}"
        f"{lang_block}"
        "      <invoicecontents>\n"
        f"{lines_xml}\n"
        "      </invoicecontents>\n"
        "    </invoice>\n"
        "  </invoices>\n"
        "</api>\n"
    )


# Backward-compat re-export. Implementation lives in proforma_pz_recovery
# (kept separate so this module stays a pure builder with no external I/O deps).
from .proforma_pz_recovery import build_pz_request_from_proforma_snapshot  # noqa: F401, E402


__all__ = [
    "ProformaSnapshot",
    "LineItem",
    "FinalInvoicePlan",
    "ProformaParseError",
    "NotAProforma",
    "BACK_REFERENCE_TEMPLATE",
    "parse_proforma_xml",
    "build_final_invoice_plan",
    "build_final_invoice_xml",
    "lines_match",
    "build_pz_request_from_proforma_snapshot",
]
