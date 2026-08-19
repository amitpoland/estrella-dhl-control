"""
statement_pdf_renderer.py — Phase 10C Statement of Account PDF renderer.
========================================================================

Pure function: takes the dict produced by
``ledger_aggregator.aggregate_statement(...)`` and emits PDF bytes.
**No I/O, no DB read, no wFirma round-trip.** The route layer is
responsible for fetching and aggregating; this module only renders.

Layout (matches docs/PHASE10B_STATEMENT_ARCHITECTURE.md design):

  * Branded masthead band — emerald → gold gradient strip with
    Estrella eyebrow + "Statement of Account" title.
  * Statement metadata strip (Issued · Period · Aging method · Currencies).
  * Customer block (right-aligned: name, country, VAT, wFirma id).
  * Per-currency section, repeated:
      - Currency header bar.
      - Totals card (left) + Aging card (right) with method label.
      - Ledger table (chronological entries; header repeats per page).
      - Unmatched-payments mini-table (only if non-empty).
  * Warnings band (only if non-empty).
  * Footer: seller name, page X of Y, "Aging method: Invoice age"
    disclaimer.

Brand tokens are hardcoded from the dashboard's Phase-7 Document Suite
palette (emerald 0B3D2E, gold C9A24B, cream FBF8F1) — keep in lockstep
with ``service/app/static/dashboard.html``'s ``ej-*`` CSS vars.

Forbidden inputs (defence-in-depth — the aggregator already excludes
these, but we re-pin here so a future direct caller cannot bypass):

  paymentstate · paymentdate · alreadypaid · remaining · paid_date

The renderer ignores any such key on every dict it walks.
"""
from __future__ import annotations

import calendar
import io
import os
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.platypus import (
    CondPageBreak, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate,
    Spacer, Table, TableStyle, Image,
)

from .financial_aging import AGING_BUCKETS_WITH_UNAVAILABLE


# ── Brand palette (emerald / gold / cream — Document Suite Phase 7) ───────

_EJ_BRAND       = colors.HexColor("#0B3D2E")  # emerald
_EJ_BRAND_2     = colors.HexColor("#0F5A45")  # deeper emerald
_EJ_BRAND_3     = colors.HexColor("#DCEDE5")  # light emerald
_EJ_GOLD        = colors.HexColor("#C9A24B")
_EJ_GOLD_2      = colors.HexColor("#B0892F")  # dark gold
_EJ_GOLD_TINT   = colors.HexColor("#F6EFD9")
_EJ_CREAM       = colors.HexColor("#FBF8F1")
_EJ_INK         = colors.HexColor("#0F172A")
_EJ_INK_2       = colors.HexColor("#475569")
_EJ_LINE        = colors.HexColor("#E2E8F0")
_EJ_RED         = colors.HexColor("#B91C1C")
_EJ_WARN_BG     = colors.HexColor("#FEF3C7")
_EJ_WARN_BORDER = colors.HexColor("#D97706")


# ── Forbidden keys (defence-in-depth) ─────────────────────────────────────

_FORBIDDEN_KEYS: Tuple[str, ...] = (
    "paymentstate",
    "paymentdate",
    "alreadypaid",
    "remaining",
    "paid_date",
)


# ── Unicode font registration (mirrors pz_pdf_export pattern) ─────────────

def _register_unicode_fonts() -> Tuple[str, str]:
    """Register a Unicode-capable font pair. Returns (regular, bold).

    Mirrors ``pz_pdf_export._register_unicode_fonts`` so Polish customer
    names render without missing-glyph squares. We register under
    distinct names (``EJStmt`` / ``EJStmt-Bold``) so the call is
    idempotent even if pz_pdf_export already registered DejaVu globally.
    """
    import reportlab as _rl
    _rl_font_dir = os.path.join(os.path.dirname(_rl.__file__), "fonts")

    # If our names are already registered (re-import path), short-circuit.
    registered = pdfmetrics.getRegisteredFontNames()
    if "EJStmt" in registered and "EJStmt-Bold" in registered:
        return "EJStmt", "EJStmt-Bold"

    candidates = [
        ("C:\\Windows\\Fonts\\DejaVuSans.ttf",
         "C:\\Windows\\Fonts\\DejaVuSans-Bold.ttf"),
        ("/Library/Fonts/DejaVuSans.ttf",
         "/Library/Fonts/DejaVuSans-Bold.ttf"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("C:\\Windows\\Fonts\\arial.ttf",
         "C:\\Windows\\Fonts\\arialbd.ttf"),
        ("/Library/Fonts/Arial Unicode.ttf",
         "/Library/Fonts/Arial Unicode.ttf"),
        (os.path.join(_rl_font_dir, "Vera.ttf"),
         os.path.join(_rl_font_dir, "VeraBd.ttf")),
    ]
    for reg, bold in candidates:
        if os.path.exists(reg) and os.path.exists(bold):
            try:
                pdfmetrics.registerFont(TTFont("EJStmt",      reg))
                pdfmetrics.registerFont(TTFont("EJStmt-Bold", bold))
                return "EJStmt", "EJStmt-Bold"
            except Exception:
                # Some font files fail to load on certain platforms —
                # try the next candidate.
                continue
    raise RuntimeError(
        "No Unicode TTF font found. Install DejaVu or verify reportlab "
        "ships Vera.ttf."
    )


_FONT_REG, _FONT_BOLD = _register_unicode_fonts()


# ── Footer band ───────────────────────────────────────────────────────────
# ONE geometry definition, consumed by both writers that draw in the footer:
# `_NumberedCanvas.save` (centred page number) and `_make_footer_drawer`
# (seller left, aging right). They used to size themselves independently,
# which is how a long seller line printed straight through "Page 1 of 2".
# The page-number band is reserved first; each side text is clipped to what
# is left, measured in points with the font it is actually drawn in.
_FOOT_Y          = 10 * mm
_FOOT_LEFT_X     = 15 * mm
_FOOT_RIGHT_X    = 195 * mm
_FOOT_CENTER_X   = 105 * mm
_FOOT_BAND_HALF  = 17 * mm          # half-width reserved for "Page X of Y"
_FOOT_GUTTER     = 3 * mm
_FOOT_SIZE       = 6.5
_FOOT_SIZE_RIGHT = 7
_FOOT_LEFT_MAX   = (_FOOT_CENTER_X - _FOOT_BAND_HALF - _FOOT_GUTTER) - _FOOT_LEFT_X
_FOOT_RIGHT_MAX  = _FOOT_RIGHT_X - (_FOOT_CENTER_X + _FOOT_BAND_HALF + _FOOT_GUTTER)


def _clip_to_width(text: str, font: str, size: float, max_w: float) -> str:
    """Trim *text* to *max_w* points, appending an ellipsis when it bites.

    A character count cannot do this job: the seller block is proportional
    text, and its length in characters says nothing about how many points
    it occupies. Measured against the font it is drawn in.
    """
    if not text:
        return ""
    if pdfmetrics.stringWidth(text, font, size) <= max_w:
        return text
    ell = "…"
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if pdfmetrics.stringWidth(text[:mid] + ell, font, size) <= max_w:
            lo = mid
        else:
            hi = mid - 1
    return (text[:lo] + ell) if lo else ""


class _NumberedCanvas(pdf_canvas.Canvas):
    """Two-pass page numbers: ``Page X of Y`` after the story is known."""

    def __init__(self, *args, **kwargs):
        pdf_canvas.Canvas.__init__(self, *args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.setFont(_FONT_REG, _FOOT_SIZE)
            self.setFillColor(_EJ_INK_2)
            self.drawCentredString(
                _FOOT_CENTER_X, _FOOT_Y,
                f"Page {self._pageNumber} of {num_pages}",
            )
            pdf_canvas.Canvas.showPage(self)
        pdf_canvas.Canvas.save(self)


# ── Helpers ────────────────────────────────────────────────────────────────

def _safe(s: Any) -> str:
    if s is None:
        return ""
    text = str(s)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _strip_forbidden(d: Any) -> Any:
    """Recursively drop forbidden keys from any dict / list. The
    aggregator never emits them, but a defence-in-depth scrub
    protects against future direct callers passing raw wFirma XML
    excerpts that happen to carry these keys."""
    if isinstance(d, dict):
        return {
            k: _strip_forbidden(v)
            for k, v in d.items()
            if k not in _FORBIDDEN_KEYS
        }
    if isinstance(d, list):
        return [_strip_forbidden(x) for x in d]
    return d


def _styles() -> Dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "eyebrow": ParagraphStyle(
            "ej_eyebrow", parent=base["Normal"],
            fontName=_FONT_BOLD, fontSize=7, leading=8,
            textColor=_EJ_GOLD_TINT, alignment=TA_LEFT,
            spaceAfter=2,
        ),
        "title": ParagraphStyle(
            "ej_title", parent=base["Title"],
            fontName=_FONT_BOLD, fontSize=20, leading=22,
            textColor=colors.white, alignment=TA_LEFT,
            spaceAfter=0,
        ),
        "subtle": ParagraphStyle(
            "ej_subtle", parent=base["Normal"],
            fontName=_FONT_REG, fontSize=8, leading=10,
            textColor=_EJ_INK_2, alignment=TA_LEFT,
        ),
        # Running text. `value` is a bold 10pt figure style and `subtle` is
        # 8pt grey -- neither reads as a sentence, so documents that actually
        # speak (the balance confirmation) get their own body style here
        # rather than borrowing one that was built for a number.
        "body": ParagraphStyle(
            "ej_body", parent=base["Normal"],
            fontName=_FONT_REG, fontSize=9, leading=12,
            textColor=_EJ_INK, alignment=TA_LEFT,
        ),
        "label": ParagraphStyle(
            "ej_label", parent=base["Normal"],
            fontName=_FONT_BOLD, fontSize=7, leading=9,
            textColor=_EJ_INK_2, alignment=TA_LEFT,
            spaceAfter=2,
        ),
        "value": ParagraphStyle(
            "ej_value", parent=base["Normal"],
            fontName=_FONT_BOLD, fontSize=10, leading=12,
            textColor=_EJ_INK, alignment=TA_LEFT,
        ),
        "section_header": ParagraphStyle(
            "ej_section_header", parent=base["Normal"],
            fontName=_FONT_BOLD, fontSize=11, leading=13,
            textColor=_EJ_BRAND, alignment=TA_LEFT,
            spaceBefore=6, spaceAfter=4,
        ),
        "warning_line": ParagraphStyle(
            "ej_warning_line", parent=base["Normal"],
            fontName=_FONT_REG, fontSize=8.5, leading=11,
            textColor=_EJ_INK, alignment=TA_LEFT,
            spaceAfter=2,
        ),
        "footer_left": ParagraphStyle(
            "ej_footer_left", parent=base["Normal"],
            fontName=_FONT_REG, fontSize=7, leading=9,
            textColor=_EJ_INK_2, alignment=TA_LEFT,
        ),
        "footer_center": ParagraphStyle(
            "ej_footer_center", parent=base["Normal"],
            fontName=_FONT_REG, fontSize=7, leading=9,
            textColor=_EJ_INK_2, alignment=TA_CENTER,
        ),
        "footer_right": ParagraphStyle(
            "ej_footer_right", parent=base["Normal"],
            fontName=_FONT_BOLD, fontSize=7, leading=9,
            textColor=_EJ_GOLD_2, alignment=TA_RIGHT,
        ),
    }


def _aging_method_label(method: str) -> str:
    """Always render a human-readable label, never the bare token."""
    if method == "due_date":
        return "Due date"
    return "Invoice age"   # only when method token is invoice_age


# ── Section builders ───────────────────────────────────────────────────────

# ── Aging vocabulary — one table for every document in this module ───────
# Order and keys come from `financial_aging`, the canonical bucket authority.
# Nothing here computes a bucket or a total; this is the label layer only.
# It replaced three hand-maintained tables (client section, supplier section,
# management analysis) that had already drifted to three different words for
# the same bucket -- "due date n/a", "Due date n/a", "Due n/a".
_BUCKET_ORDER: Tuple[str, ...] = tuple(AGING_BUCKETS_WITH_UNAVAILABLE)
_BUCKET_LABELS: Dict[str, str] = {
    "not_due":              "Not due",
    "b_1_30":               "1–30",
    "b_31_60":              "31–60",
    "b_61_90":              "61–90",
    "b_91_180":             "91–180",
    "b_181_365":            "181–365",
    "b_365_plus":           "365+",
    "due_date_unavailable": "Due date n/a",
}
if set(_BUCKET_LABELS) != set(_BUCKET_ORDER):        # pragma: no cover
    raise RuntimeError(
        "aging bucket labels drifted from financial_aging: %s"
        % (sorted(set(_BUCKET_LABELS) ^ set(_BUCKET_ORDER)),)
    )

# Spellings older payloads used before the canonical keys landed. Reading a
# superseded key keeps an archived statement printing its real number instead
# of a confident 0.00; it never invents one.
_BUCKET_LEGACY_KEYS: Dict[str, Tuple[str, ...]] = {
    "not_due":    ("current",),
    "b_1_30":     ("1_30",),
    "b_31_60":    ("31_60",),
    "b_61_90":    ("61_90",),
    "b_365_plus": ("90_plus",),
}


def _bucket_value(aging: Dict[str, Any], key: str) -> str:
    """Read one bucket out of an aging block. Never computes, never sums."""
    val = aging.get(key)
    if val in (None, ""):
        for legacy in _BUCKET_LEGACY_KEYS.get(key, ()):
            val = aging.get(legacy)
            if val not in (None, ""):
                break
    return str(val) if val not in (None, "") else "0.00"


def _aging_rows(aging: Dict[str, Any]) -> List[Tuple[str, str]]:
    """Aging card rows in canonical order — hide an empty ``due date n/a``
    line, always keep the total the aggregator already computed.

    The column sums to its own printed total because ``total`` is the block's
    open balance (financial_aging: sum of lanes == open balance, undated lane
    included), so the undated line belongs above the rule with the buckets.
    Nothing is added up here — a renderer that re-totals a financial column
    is a second accounting engine.
    """
    aging = aging or {}
    rows: List[Tuple[str, str]] = []
    for key in _BUCKET_ORDER:
        if key == "due_date_unavailable" and aging.get("due_date_unavailable") in (
            None, "", "0", "0.00",
        ):
            continue
        rows.append((_BUCKET_LABELS[key], _bucket_value(aging, key)))
    rows.append(("Total", str(aging.get("total") or "0.00")))
    return rows


def _masthead_flowable(
    stmt: Dict[str, Any],
    styles: Dict[str, ParagraphStyle],
    *,
    seller: Optional[Dict[str, str]] = None,
    logo_path: str = "",
    title: str = "Statement of Account",
):
    """Brand band: reuse document-suite logo asset when present;
    otherwise CompanyProfile / seller name (no invented EJ glyph).

    *title* is the only thing that varies between the three documents this
    module renders — the logo band, gold rule and typography are shared so
    Supplier Statement and Management Analysis are literally the same brand
    code path as the Client Statement (PR #1176)."""
    seller = seller or {}
    brand = (seller.get("name") or "").strip() or "Estrella Jewels"

    if logo_path and os.path.isfile(logo_path):
        try:
            mark = Image(logo_path, width=14 * mm, height=14 * mm, kind="proportional")
        except Exception:
            mark = Paragraph(
                f"<b>{_safe(brand)}</b>",
                ParagraphStyle(
                    "logo_wordmark", fontName=_FONT_BOLD, fontSize=11,
                    leading=13, textColor=_EJ_GOLD, alignment=TA_LEFT,
                ),
            )
    else:
        mark = Paragraph(
            f"<b>{_safe(brand)}</b>",
            ParagraphStyle(
                "logo_wordmark", fontName=_FONT_BOLD, fontSize=11,
                leading=13, textColor=_EJ_GOLD, alignment=TA_LEFT,
            ),
        )

    text_block = [
        Paragraph("ESTRELLA JEWELS · DOCUMENT SUITE", styles["eyebrow"]),
        Paragraph(title, styles["title"]),
    ]

    band = Table(
        [[mark, text_block]],
        colWidths=[28 * mm, 152 * mm],
    )
    band.setStyle(TableStyle([
        ("BACKGROUND",     (0, 0), (-1, -1), _EJ_BRAND),
        ("LINEAFTER",      (1, 0), (1, 0), 3, _EJ_GOLD),
        ("VALIGN",         (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",    (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",   (0, 0), (-1, -1), 8),
        ("TOPPADDING",     (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 6),
    ]))
    return band


def _meta_strip_flowable(stmt: Dict[str, Any], styles):
    """Metadata strip: Issued / As-of / Period / Currency + Source / Freshness."""
    period = stmt.get("period") or {}
    period_str = f"{period.get('from') or '—'} → {period.get('to') or '—'}"
    currencies = ", ".join(stmt.get("currencies") or []) or "—"
    aging_blocks = stmt.get("aging_per_currency") or {}
    method_token = stmt.get("aging_method") or "due_date"
    for v in aging_blocks.values():
        method_token = v.get("method", method_token) or method_token
        break
    method_label = _aging_method_label(method_token)
    freshness = stmt.get("freshness")
    if isinstance(freshness, dict):
        freshness_s = str(
            freshness.get("as_of")
            or freshness.get("period_end")
            or "—"
        )
    else:
        freshness_s = str(freshness or "—")
    recon = stmt.get("reconciliation_status") or "—"
    source = stmt.get("source") or "—"

    row1 = [
        ("Issued",     _safe(stmt.get("issued_at") or stmt.get("generated_at") or "")),
        ("As of",      _safe(stmt.get("as_of") or "")),
        ("Period",     _safe(period_str)),
        ("Currencies", _safe(currencies)),
    ]
    row2 = [
        ("Source",     _safe(source)),
        ("Freshness",  _safe(freshness_s)),
        ("Reconciled", _safe(recon)),
        ("Aging",      _safe(method_label)),
    ]
    labels1 = [Paragraph(lbl, styles["label"]) for lbl, _ in row1]
    vals1 = [Paragraph(f"<b>{val or '—'}</b>", styles["value"]) for _, val in row1]
    labels2 = [Paragraph(lbl, styles["label"]) for lbl, _ in row2]
    vals2 = [Paragraph(f"<b>{val or '—'}</b>", styles["value"]) for _, val in row2]
    t = Table([labels1, vals1, labels2, vals2], colWidths=[45 * mm] * 4)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), _EJ_CREAM),
        ("BOX",           (0, 0), (-1, -1), 0.4, _EJ_LINE),
        ("INNERGRID",     (0, 0), (-1, -1), 0.4, _EJ_LINE),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def _customer_block_flowable(
    stmt: Dict[str, Any],
    styles,
    *,
    customer_facing: bool = True,
    label: str = "Customer",
):
    c = stmt.get("contractor") or {}
    name = _safe(c.get("name") or "")
    street = _safe(c.get("street") or "")
    city = _safe(c.get("city") or "")
    postal = _safe(c.get("postal_code") or "")
    country = _safe(c.get("country") or "")
    vat_id = _safe(c.get("vat_id") or "")

    city_line = ", ".join(p for p in (postal, city) if p)
    addr_bits = [name]
    if street:
        addr_bits.append(street)
    if city_line:
        addr_bits.append(city_line)
    if country:
        addr_bits.append(country)
    addr_bits.append(f"VAT/Tax ID: {vat_id or '—'}")
    if not customer_facing:
        wfid = _safe(c.get("wfirma_contractor_id") or "")
        if wfid:
            addr_bits.append(f"wFirma id · {wfid}")

    body = "<br/>".join(
        f"<font size='10'>{bit}</font>" if idx == 0
        else f"<font size='9' color='#475569'>{bit}</font>"
        for idx, bit in enumerate(addr_bits)
    )
    rows = [[Paragraph(f"<b>{_safe(label)}</b><br/>{body}", styles["subtle"])]]
    t = Table(rows, colWidths=[180 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.4, _EJ_LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


# ── Ledger vocabulary — one table shape for every document here ──────
_TYPE_LABELS = {
    "opening_balance": "B/F",
    "invoice":         "Invoice",
    "correction":      "Credit note",
    "credit_note":     "Credit note",
    "proforma":        "Proforma",
    "expense":         "Expense",
    "payment":         "Payment",
}


def _type_label(raw: Any) -> str:
    key = str(raw or "").strip().lower()
    return _TYPE_LABELS.get(key) or key.replace("_", " ").strip() or "—"


def _first(entry: Dict[str, Any], keys) -> str:
    for k in keys:
        v = str(entry.get(k) or "").strip()
        if v:
            return v
    return ""


# Everything that differs between the receivable and the payable statement is
# DATA, not a second renderer. Adding a third side means adding a dict here.
_SIDE_CFG: Dict[str, Dict[str, Any]] = {
    "ar": {
        "party":            "Customer",
        "credits_label":    "Customer credits",
        "net_label":        "Net receivable",
        # Same words as the supplier statement and as the operator
        # screen: one document system does not use two names for cash it
        # could not apply. The JSON key and the warning event keep their
        # own (`unmatched_*`) names -- see the module docstring.
        "unmatched_title":  "Unapplied payments",
        "unmatched_type":   "Unapplied payment",
        # A ledger row is identified by its document number and nothing
        # else. Unapplied cash has no document, so its disclosure falls
        # back to the wFirma object id -- the only handle it has, and the
        # one the counterparty needs in order to name the payment.
        "doc_keys":         ("doc_number",),
        "unmatched_doc_keys": ("doc_number", "wfirma_doc_id"),
        "ref_keys":         ("reference", "linked_invoice"),
        # `totals["outstanding"]` on the AR side is the aggregator's PERIOD
        # CLOSING alias, not a position. There is deliberately no fallback:
        # printing a period figure under "Position" is the exact confusion
        # this card exists to end.
        "position_fallback": (),
        "empty_sentence":   "No invoices or payments for this contractor in "
                            "the selected period.",
        "confirm_sentence": "Our books show the net position above as "
                            "receivable by us from you.",
        # Printed on the confirmation only when such cash exists. Without
        # it the reader sees a position that is smaller than their own
        # ledger implies, with nothing on the page explaining the gap.
        "unapplied_sentence": "Payments received from you that we could not "
                              "match to a document are listed above. They "
                              "are disclosed, not deducted: the position "
                              "stated above does not include them.",
        "titles": {
            "soa":          "Statement of Account",
            "monthly":      "Monthly Statement of Account",
            "ledger":       "Detailed Ledger",
            "confirmation": "Balance Confirmation",
        },
    },
    "ap": {
        "party":            "Supplier",
        "credits_label":    "Supplier credits",
        "net_label":        "Net payable",
        "unmatched_title":  "Unapplied payments",
        "unmatched_type":   "Unapplied payment",
        # Same split as AR. A matched payment row in the AP ledger has an
        # empty `doc_number` and a `wfirma_doc_id`, so a shared fallback
        # printed the wFirma id straight onto a supplier-facing page.
        "doc_keys":         ("doc_number",),
        "unmatched_doc_keys": ("doc_number", "wfirma_doc_id"),
        "ref_keys":         ("reference",),
        "position_fallback": (
            ("Expenses (gross)", "gross_payable"),
            ("Supplier credits", "supplier_credits"),
            ("Payments applied", "payments_applied"),
            ("Outstanding",      "outstanding"),
            ("Net payable",      "net_payable"),
        ),
        "empty_sentence":   "No expenses or payments for this supplier in "
                            "the selected period.",
        "confirm_sentence": "Our books show the net position above as "
                            "payable by us to you.",
        "unapplied_sentence": "Payments we made to you that we could not "
                              "match to a document are listed above. They "
                              "are disclosed, not deducted: the position "
                              "stated above does not include them.",
        "titles": {
            "soa":          "Supplier Statement",
            "monthly":      "Monthly Supplier Statement",
            "ledger":       "Detailed Supplier Ledger",
            "confirmation": "Supplier Balance Confirmation",
        },
    },
}

# `detailed` adds the Reference and Status columns; `ledger` False drops the
# transaction table entirely (a confirmation is a balance, not a history).
# `period_close` marks the balance-forward product: a statement issued FOR a
# named calendar month, whose spine is opening + debits - credits = closing.
# Without it `monthly` was `soa` with a different word in the title -- one
# document wearing two names, which is the duplicate-product case the
# single-authority rule exists to prevent. It is a presentation flag: it
# selects wording and emphasis, never arithmetic and never a second formula.
_DOC_CFG: Dict[str, Dict[str, Any]] = {
    "soa":          {"detailed": False, "ledger": True,  "confirm": False,
                     "period_close": False},
    "monthly":      {"detailed": False, "ledger": True,  "confirm": False,
                     "period_close": True},
    "ledger":       {"detailed": True,  "ledger": True,  "confirm": False,
                     "period_close": False},
    "confirmation": {"detailed": False, "ledger": False, "confirm": True,
                     "period_close": False},
}

_SOA_HEADERS = ["Date", "Due date", "Document", "Type",
                "Debit", "Credit", "Balance"]
_SOA_WIDTHS = [20 * mm, 20 * mm, 34 * mm, 24 * mm, 26 * mm, 26 * mm, 30 * mm]
_LED_HEADERS = ["Date", "Due date", "Document", "Type", "Reference",
                "Debit", "Credit", "Running Balance", "Status"]
# Nine columns in 180mm only fit if the grid drops a point; at 8pt the
# measured render broke "Running Balance" and the document numbers across two
# lines. The detailed ledger therefore renders one point smaller -- a table
# property, not a second table builder.
# Widths are measured with reportlab.pdfbase.pdfmetrics.stringWidth, not
# guessed. The binding token in each column is the BOLD header, not the body
# text: at 7pt Helvetica-Bold "Running Balance" is 20.17mm of ink and an ISO
# date is 12.63mm, so with the 3pt padding either side (2.12mm) they need
# 22.29mm and 14.75mm -- which is why those columns are 26mm and 18mm and not
# tighter. Every column carries its widest real token; they sum to 180mm.
# Status is sized against the REAL backend vocabulary in
# ledger_aggregator.derive_presentation_status -- "Credit / Offset" (17.35mm
# with padding) and "Status Conflict" (18.04mm) are the tokens that must not
# wrap; only the rare "Due Date Unavailable" (26.14mm) breaks, and at 20mm it
# breaks cleanly between its words. The 5mm comes off Document and Reference,
# which hold wFirma document numbers of ~15 characters at most.
_LED_WIDTHS = [18 * mm, 18 * mm, 24 * mm, 19 * mm, 23 * mm,
               16 * mm, 16 * mm, 26 * mm, 20 * mm]
_LED_FONT_SIZE = 7


def side_cfg(side: str) -> Dict[str, Any]:
    try:
        return _SIDE_CFG[side]
    except KeyError:
        raise ValueError("unknown statement side %r" % (side,))


def doc_cfg(document: str) -> Dict[str, Any]:
    try:
        return _DOC_CFG[document]
    except KeyError:
        raise ValueError("unknown statement document %r" % (document,))


def _month_label(period: Optional[Dict[str, Any]]) -> str:
    """The calendar-month name IF the period is exactly that whole month.

    Returns "" for anything else -- a part month, a quarter, a rolling
    window, an unparseable date. Naming a month is an assertion about which
    window the figures cover, and a monthly statement that prints
    "July 2026" over a 12-31 July range misstates its own scope. Presentation
    only: no date is invented and no figure is touched.
    """
    frm = str((period or {}).get("from") or "").strip()
    to = str((period or {}).get("to") or "").strip()
    if len(frm) < 10 or len(to) < 10:
        return ""
    try:
        y0, m0, d0 = int(frm[0:4]), int(frm[5:7]), int(frm[8:10])
        y1, m1, d1 = int(to[0:4]), int(to[5:7]), int(to[8:10])
    except ValueError:
        return ""
    if (y0, m0) != (y1, m1) or d0 != 1 or not 1 <= m1 <= 12:
        return ""
    if d1 != calendar.monthrange(y1, m1)[1]:
        return ""
    return "%s %d" % (calendar.month_name[m1], y1)


def statement_title(side: str, document: str,
                    stmt: Optional[Dict[str, Any]] = None) -> str:
    """Product title, with the month appended for the balance-forward product.

    `stmt` is optional so the two-argument callers keep working; when it is
    given and the period really is one whole calendar month, the monthly
    statement says WHICH month on its face. A monthly statement whose period
    is not a whole month keeps the plain title and carries the period notice
    instead -- see `_period_integrity_flowables`.
    """
    base = side_cfg(side)["titles"][document]
    if doc_cfg(document)["period_close"] and stmt:
        month = _month_label(stmt.get("period"))
        if month:
            return "%s · %s" % (base, month)
    return base


def _num(value: Any) -> str:
    """Print what the aggregator produced. No coercion, no arithmetic."""
    return str(value) if value not in (None, "") else "0.00"


def _activity_rows(totals: Dict[str, Any], *,
                   period_close: bool = False) -> List[Tuple[str, str]]:
    """What MOVED inside the window. Position keys are deliberately absent —
    an activity card that borrows a position figure is precisely how a period
    number gets read as a current one.

    On the balance-forward product the same four figures are labelled as the
    chain they form, so a counterparty can verify the month closes:
    opening + debits - credits = closing. The operators are LABELS. Nothing
    is added here; every value is printed exactly as the aggregator produced
    it, and a renderer that re-derived the closing balance would be a second
    accounting engine.
    """
    if period_close:
        return [
            ("Opening balance",   _num(totals.get("opening_balance"))),
            ("+ Period debits",   _num(totals.get("period_debits"))),
            ("- Period credits",  _num(totals.get("period_credits"))),
            ("= Closing balance", _num(totals.get("closing_balance"))),
            ("Entries",           str(totals.get("entry_count") or 0)),
        ]
    return [
        ("Opening balance", _num(totals.get("opening_balance"))),
        ("Period debits",   _num(totals.get("period_debits"))),
        ("Period credits",  _num(totals.get("period_credits"))),
        ("Closing balance", _num(totals.get("closing_balance"))),
        ("Entries",         str(totals.get("entry_count") or 0)),
    ]


def _position_rows(pos: Dict[str, Any], totals: Dict[str, Any],
                   cfg: Dict[str, Any]):
    """GROSS EXPOSURE − CREDITS = NET POSITION, straight from the aggregator.

    Returns (rows, rule_above). When the payload predates
    `position_per_currency` the side's declared fallback keys are read
    instead; a side with no honest fallback simply gets no card.
    """
    if pos:
        # Order is the whole point. overdue + not-yet-due + no-due-date sum
        # to GROSS (measured 8136 + 1230 + 738 = 10104), and the aggregator
        # says so itself with aging_basis="gross_before_credits". Printed
        # below the net line they read as a breakdown OF net, so an offset
        # account shows a net of nil sitting above three large arrears
        # figures. Under gross they read as what they are, and credits then
        # net follow as the reconciliation.
        rows = [("Gross exposure",       _num(pos.get("gross_exposure"))),
                ("of which overdue",     _num(pos.get("overdue"))),
                ("of which not yet due", _num(pos.get("not_due")))]
        if pos.get("due_date_unavailable") not in (None, "", "0.00"):
            rows.append(("of which no due date",
                         _num(pos.get("due_date_unavailable"))))
        credits_at = len(rows)
        rows.append((cfg["credits_label"], _num(pos.get("credit_balance"))))
        rows.append((cfg["net_label"],     _num(pos.get("net_position"))))
        return rows, (credits_at, credits_at + 1)
    fallback = cfg["position_fallback"]
    if not fallback:
        return [], -1
    rows = [(label, _num(totals.get(key))) for label, key in fallback]
    return rows, len(rows) - 1


def _presentation_note(pos: Dict[str, Any]) -> str:
    """Say out loud what an offset account is, so a covered balance can never
    read as arrears just because the aging table is gross-based."""
    state = str(pos.get("presentation_state") or "").strip().lower()
    if state == "offset":
        return ("This account is offset: the gross exposure above is fully "
                "covered by credits, so the net position is nil. The aging "
                "table is gross, before credits — it is not arrears.")
    if state == "credit":
        return ("This account is in credit: credits exceed the gross "
                "exposure. Nothing is outstanding.")
    return ""


def _ledger_rows(entries: List[Dict[str, Any]], cfg: Dict[str, Any],
                 *, detailed: bool) -> List[List[str]]:
    rows: List[List[str]] = []
    for e in entries:
        row = [
            str(e.get("date") or ""),
            str(e.get("due_date") or "—"),
            _first(e, cfg["doc_keys"]) or "—",
            _type_label(e.get("type")),
        ]
        if detailed:
            row.append(_first(e, cfg["ref_keys"]) or "—")
        row += [
            _num(e.get("debit")),
            _num(e.get("credit")),
            _num(e.get("running_balance")),
        ]
        if detailed:
            row.append(str(e.get("presentation_status")
                           or e.get("status") or "—"))
        rows.append(row)
    return rows


def _overpaid_ids(stmt: Dict[str, Any]):
    """Warnings are dicts on the receivable side and plain strings on the
    payable side; only the dict form can name a document."""
    out = set()
    for w in (stmt.get("warnings") or []):
        if isinstance(w, dict) and w.get("event") == "overpayment_on_invoice":
            out.add(w.get("wfirma_doc_id"))
    out.discard(None)
    return out


def _currency_section_flowables(
    stmt: Dict[str, Any],
    ccy:  str,
    styles,
    *,
    side: str = "ar",
    document: str = "soa",
) -> List[Any]:
    """The per-currency block for EVERY statement product on EVERY side:
    currency bar, activity card, position card, aging card, then — unless the
    document is a balance confirmation — the ledger and any payment that could
    not be applied.

    Currencies are rendered side by side and never summed. `side` and
    `document` select vocabulary and columns; they never select arithmetic,
    which belongs entirely to the aggregator.
    """
    cfg = side_cfg(side)
    dcfg = doc_cfg(document)
    out: List[Any] = []

    totals = (stmt.get("totals_per_currency")   or {}).get(ccy) or {}
    aging  = (stmt.get("aging_per_currency")    or {}).get(ccy) or {}
    pos    = (stmt.get("position_per_currency") or {}).get(ccy) or {}

    month = _month_label(stmt.get("period")) if dcfg["period_close"] else ""
    activity_card = _kv_card("Period activity",
        _activity_rows(totals, period_close=dcfg["period_close"]), styles,
        subtitle=("balance forward · %s" % month if month
                  else "balance forward · period as stated above")
        if dcfg["period_close"] else "movement inside the period",
        rule_above=3)
    prows, prule = _position_rows(pos, totals, cfg)
    stack: List[List[Any]] = [[activity_card]]
    if prows:
        position_card = _kv_card("Position", prows, styles, rule_above=prule,
                                 subtitle="gross less credits · as of %s"
                                          % (stmt.get("as_of") or ""))
        stack += [[Spacer(1, 6)], [position_card]]
    left_stack = Table(stack, colWidths=[90 * mm])
    left_stack.setStyle(TableStyle([
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 0),
        ("TOPPADDING",    (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    arows = _aging_rows(aging)
    aging_card = _kv_card(
        "Aging · %s" % _aging_method_label(aging.get("method")
                                           or stmt.get("aging_method")
                                           or "due_date"),
        arows, styles,
        subtitle="gross · before credits",
        rule_above=len(arows) - 1,
    )
    cards = Table([[left_stack, aging_card]], colWidths=[90 * mm, 90 * mm])
    cards.setStyle(TableStyle([
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    out.append(KeepTogether([_currency_bar("Currency · %s" % ccy),
                             Spacer(1, 4), cards]))

    note = _presentation_note(pos)
    if note:
        out.append(Spacer(1, 4))
        out.append(Paragraph("<i>%s</i>" % _safe(note), styles["subtle"]))
    out.append(Spacer(1, 6))

    # The confirmation carries no ledger -- it asks about ONE number, and a
    # document listing takes the reader's eye off it. Unapplied cash is a
    # different matter and is disclosed on every product: see below.
    if dcfg["ledger"]:
        entries = (stmt.get("entries_per_currency") or {}).get(ccy) or []
        detailed = dcfg["detailed"]
        overpaid = _overpaid_ids(stmt)
        shade = [i for i, e in enumerate(entries)
                 if e.get("wfirma_doc_id") in overpaid] if overpaid else []
        out.extend(_titled_grid(
            Paragraph("<b>Ledger</b>", styles["section_header"]),
            _grid_table(
                _LED_HEADERS if detailed else _SOA_HEADERS,
                _ledger_rows(entries, cfg, detailed=detailed),
                _LED_WIDTHS if detailed else _SOA_WIDTHS,
                # Detailed: money is columns 5-7; column 8 (Status) is text.
                right_from=5 if detailed else 4,
                right_to=8 if detailed else None,
                shade_rows=shade,
                font_size=_LED_FONT_SIZE if detailed else 8,
            )))
        if not entries:
            out.append(Paragraph(
                "<i>No entries in this currency for the selected period.</i>",
                styles["subtle"]))

    unmatched = (stmt.get("unmatched_payments_per_currency") or {}).get(ccy) or []
    if unmatched:
        urows = [[
            str(u.get("date") or ""),
            _first(u, cfg["unmatched_doc_keys"]) or "—",
            cfg["unmatched_type"],
            _num(u.get("value")),
        ] for u in unmatched]
        out.append(Spacer(1, 6))
        out.extend(_titled_grid(
            Paragraph("<b>%s</b>" % _safe(cfg["unmatched_title"]),
                      styles["section_header"]),
            _grid_table(["Date", "Document", "Type", "Amount"], urows,
                        [24 * mm, 46 * mm, 60 * mm, 50 * mm],
                        right_from=3)))
    out.append(Spacer(1, 8))
    return out


def _warnings_flowables(stmt: Dict[str, Any], styles) -> List[Any]:
    warnings = stmt.get("warnings") or []
    if not warnings:
        return []
    out: List[Any] = []
    out.append(Spacer(1, 6))
    out.append(Paragraph(
        "<b><font color='#B45309'>Warnings</font></b> · operator should "
        "review",
        styles["section_header"],
    ))
    rows = []
    for w in warnings:
        if not isinstance(w, dict):
            continue
        event = _safe(w.get("event") or "")
        # Build a single line of `key: value` extras (excluding event).
        extras = []
        for k, v in w.items():
            if k == "event":
                continue
            extras.append(f"{_safe(k)}: {_safe(v)}")
        line = f"<b>{event}</b>"
        if extras:
            line += " · " + " · ".join(extras)
        rows.append([Paragraph(line, styles["warning_line"])])
    t = Table(rows, colWidths=[180*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND",     (0,0), (-1,-1), _EJ_WARN_BG),
        ("BOX",            (0,0), (-1,-1), 0.6, _EJ_WARN_BORDER),
        ("LEFTPADDING",    (0,0), (-1,-1), 8),
        ("RIGHTPADDING",   (0,0), (-1,-1), 8),
        ("TOPPADDING",     (0,0), (-1,-1), 4),
        ("BOTTOMPADDING",  (0,0), (-1,-1), 4),
        ("LINEBELOW",      (0,0), (-1,-2), 0.2, _EJ_WARN_BORDER),
    ]))
    out.append(t)
    return out


def _period_integrity_flowables(stmt: Dict[str, Any], styles,
                                *, document: str = "soa") -> List[Any]:
    """Only for the balance-forward product, and only when its period is NOT
    one whole calendar month. The figures are right either way; what would be
    wrong is letting the word "Monthly" describe a window it does not cover.
    """
    if not doc_cfg(document)["period_close"]:
        return []
    if _month_label(stmt.get("period")):
        return []
    p = stmt.get("period") or {}
    return [
        Spacer(1, 4),
        Paragraph(
            "<i>Issued for %s to %s, which is not a single whole calendar "
            "month. The balances below cover exactly that window · read the "
            "period, not the word &quot;monthly&quot;.</i>"
            % (_safe(p.get("from") or "—"), _safe(p.get("to") or "—")),
            styles["subtle"]),
    ]


def _empty_notice_flowables(stmt: Dict[str, Any], styles,
                            *, side: str = "ar") -> List[Any]:
    if (stmt.get("currencies") or []):
        return []
    return [
        Spacer(1, 12),
        Paragraph("<i>%s</i>" % _safe(side_cfg(side)["empty_sentence"]),
                  styles["subtle"]),
    ]


def _confirmation_flowables(stmt: Dict[str, Any], styles,
                            *, side: str = "ar") -> List[Any]:
    """The formal agree / disagree block.

    This is a counterparty balance confirmation, not an audit confirmation: it
    is not issued under ISA 505 / SA 505, it is not sent or collected by an
    auditor, and no reply is not agreement. Both statements are printed on the
    document so neither can be implied away later.
    """
    cfg = side_cfg(side)
    lines = [
        Spacer(1, 10),
        _currency_bar("Confirmation of balance"),
        Spacer(1, 6),
        Paragraph(
            "%s Please confirm the position stated above by ticking ONE box, "
            "signing, and returning this page."
            % _safe(cfg["confirm_sentence"]), styles["body"]),
    ]
    if any((stmt.get("unmatched_payments_per_currency") or {}).values()):
        lines.append(Spacer(1, 6))
        lines.append(Paragraph(
            "<i>%s</i>" % _safe(cfg["unapplied_sentence"]), styles["body"]))
    lines += [
        Spacer(1, 8),
        Paragraph("[    ]&nbsp;&nbsp;<b>AGREED</b> — the balance above "
                  "agrees with our books.", styles["body"]),
        Spacer(1, 4),
        Paragraph("[    ]&nbsp;&nbsp;<b>NOT AGREED</b> — our books show a "
                  "different balance. Details:", styles["body"]),
        Spacer(1, 16),
    ]
    sig = Table([
        ["Name", "", "Position", ""],
        ["Signature", "", "Date", ""],
    ], colWidths=[22 * mm, 68 * mm, 22 * mm, 68 * mm],
        rowHeights=[14 * mm] * 2)
    sig.setStyle(TableStyle([
        ("FONTNAME",      (0, 0), (-1, -1), _FONT_REG),
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
        ("TEXTCOLOR",     (0, 0), (-1, -1), _EJ_INK_2),
        ("VALIGN",        (0, 0), (-1, -1), "BOTTOM"),
        ("LINEBELOW",     (1, 0), (1, -1), 0.5, _EJ_LINE),
        ("LINEBELOW",     (3, 0), (3, -1), 0.5, _EJ_LINE),
        ("LEFTPADDING",   (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    lines.append(sig)
    lines.append(Spacer(1, 8))
    lines.append(Paragraph(
        "<i>This is a commercial balance confirmation between the two "
        "parties. It is not an auditor's confirmation request and is not "
        "issued under ISA 505 / SA 505. No reply does not constitute "
        "agreement.</i>", styles["subtle"]))
    return lines


def _make_footer_drawer(
    stmt: Dict[str, Any],
    *,
    seller: Optional[Dict[str, str]] = None,
):
    """Returns a closure suitable for ``onFirstPage`` / ``onLaterPages``.

    Seller line reuses CompanyProfile / packing ``_seller_from_company``
    fields passed by the route — no duplicated hardcoded legal block.
    """
    aging_blocks = stmt.get("aging_per_currency") or {}
    method_token = stmt.get("aging_method") or "due_date"
    for v in aging_blocks.values():
        method_token = v.get("method", method_token) or method_token
        break
    method_label = _aging_method_label(method_token)
    generated_at = stmt.get("generated_at") or ""
    seller = seller or {}
    seller_name = (seller.get("name") or "").strip() or "Estrella Jewels"
    seller_addr = " · ".join(
        p for p in (
            (seller.get("addr") or "").strip(),
            (seller.get("city") or "").strip(),
            (seller.get("country") or "").strip(),
        ) if p
    )
    seller_vat = (seller.get("vat") or "").strip()
    left = seller_name
    if seller_addr:
        left = f"{seller_name} · {seller_addr}"
    if seller_vat:
        left = f"{left} · VAT {seller_vat}"
    # Clip both side texts out of the page-number band rather than letting
    # them run into it. Same band constants the page number is drawn from.
    left = _clip_to_width(left, _FONT_REG, _FOOT_SIZE, _FOOT_LEFT_MAX)
    right = _clip_to_width(f"Aging: {method_label} · {generated_at}",
                           _FONT_BOLD, _FOOT_SIZE_RIGHT, _FOOT_RIGHT_MAX)

    def _drawer(canvas, doc):
        canvas.saveState()
        canvas.setFont(_FONT_REG, _FOOT_SIZE)
        canvas.setFillColor(_EJ_INK_2)
        canvas.drawString(_FOOT_LEFT_X, _FOOT_Y, left)
        canvas.setFont(_FONT_BOLD, _FOOT_SIZE_RIGHT)
        canvas.setFillColor(_EJ_GOLD_2)
        canvas.drawRightString(_FOOT_RIGHT_X, _FOOT_Y, right)
        canvas.restoreState()
    return _drawer


# ── Public entry point ────────────────────────────────────────────────────

def render_statement_pdf(
    statement: Dict[str, Any],
    *,
    customer_facing: bool = True,
    seller: Optional[Dict[str, str]] = None,
    logo_path: str = "",
    document: str = "soa",
) -> bytes:
    """Render a Phase 10B Statement-of-Account dict to PDF bytes.

    *document* selects which product of the statement suite is produced --
    ``soa`` (default), ``monthly``, ``ledger`` or ``confirmation``. All four
    read the SAME statement dict and print the SAME figures; only the columns,
    the title and the closing block differ. A confirmation is deliberately not
    a statement with a signature line bolted on: it drops the transaction
    history so the counterparty confirms a position, not a history.

    Pure relative to ledger arithmetic: no wFirma / no re-aggregation.
    Optional *seller* / *logo_path* are presentation inputs supplied by
    the route from CompanyProfile + the shared document-suite asset.

    When *customer_facing* is True (default for the PDF route): omit
    wFirma contractor id and DQ / implementation warnings.
    """
    if not isinstance(statement, dict):
        raise ValueError("statement must be a dict produced by aggregate_statement")
    title = statement_title("ar", document, statement)

    # Defence-in-depth: drop any forbidden keys before rendering.
    stmt = _strip_forbidden(statement)
    styles = _styles()
    seller = seller or {}

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=15*mm, rightMargin=15*mm,
        topMargin=18*mm,  bottomMargin=15*mm,
        title=title,
        author=(seller.get("name") or "Estrella Jewels"),
    )

    story: List[Any] = []
    story.append(_masthead_flowable(
        stmt, styles, seller=seller, logo_path=logo_path or "", title=title,
    ))
    story.append(Spacer(1, 4))
    story.append(_meta_strip_flowable(stmt, styles))
    story.append(Spacer(1, 6))
    story.append(_customer_block_flowable(
        stmt, styles, customer_facing=customer_facing,
    ))
    story.append(Spacer(1, 8))
    story.extend(_period_integrity_flowables(stmt, styles, document=document))

    for ccy in (stmt.get("currencies") or []):
        story.extend(_currency_section_flowables(
            stmt, ccy, styles, side="ar", document=document,
        ))

    story.extend(_empty_notice_flowables(stmt, styles, side="ar"))

    if doc_cfg(document)["confirm"]:
        story.extend(_confirmation_flowables(stmt, styles, side="ar"))

    # Customer PDF: DQ / operator warnings stay on JSON / internal UI only.
    if not customer_facing:
        story.extend(_warnings_flowables(stmt, styles))

    try:
        footer = _make_footer_drawer(stmt, seller=seller)
        doc.build(
            story, onFirstPage=footer, onLaterPages=footer,
            canvasmaker=_NumberedCanvas,
        )
    except Exception as exc:
        raise RuntimeError(f"reportlab build failed: {exc}") from exc

    pdf_bytes = buf.getvalue()
    if not pdf_bytes.startswith(b"%PDF-"):
        raise RuntimeError(
            "reportlab produced output that does not look like a PDF"
        )
    return pdf_bytes


# ══════════════════════════════════════════════════════════════════════════
# Supplier Statement + Management Analysis
# ══════════════════════════════════════════════════════════════════════════
#
# Both live in this module on purpose: they reuse `_styles`, the masthead,
# the footer drawer and the already-registered `EJStmt` fonts, so all three
# documents are one brand implementation. Neither renderer computes money —
# every figure below is a string the aggregator / analytics layer already
# produced and the screen already shows (screen DTO == PDF DTO).

# Aging buckets for every document below come from the single
# `_BUCKET_ORDER` / `_BUCKET_LABELS` table near the top of this module,
# which takes its key order from `financial_aging`. The AP-local copy that
# used to sit here is gone: two tables meant two vocabularies.

# Exposure tables are capped so one currency cannot push the report to 200
# pages. The cap is printed whenever it bites — a silently truncated exposure
# table reads as "this is everyone", which is exactly the wrong conclusion.
_EXPOSURE_ROWS = 25


def _kv_card(title: str, rows: List[Tuple[str, str]], styles, *,
             rule_above=-1, width: float = 85 * mm,
             subtitle: str = ""):
    """Label/value card — the Totals and Aging cards are both this shape.

    *rule_above* draws the brand rule above that body row (0-based over
    *rows*), used to set a total apart from the lines that make it up. It
    accepts a sequence as well as a single index, because a card that
    reconciles in two stages (buckets → dated total → gross) needs a rule at
    each stage; one rule leaves the reader guessing which lines the second
    figure was built from.
    """
    head = f"<b>{_safe(title)}</b>"
    if subtitle:
        head += (f"<br/><font size='7' color='#B0892F'>"
                 f"{_safe(subtitle)}</font>")
    data = [[Paragraph(head, styles["section_header"]), ""]]
    for lbl, val in rows:
        data.append([
            Paragraph(f"<font color='#475569'>{_safe(lbl)}</font>",
                      ParagraphStyle("kvk", fontName=_FONT_REG, fontSize=9,
                                     leading=11, alignment=TA_LEFT)),
            Paragraph(f"<font name='{_FONT_BOLD}'>{_safe(val)}</font>",
                      ParagraphStyle("kvv", fontName=_FONT_BOLD, fontSize=10,
                                     leading=12, alignment=TA_RIGHT)),
        ])
    t = Table(data, colWidths=[width * 0.55, width * 0.45])
    style = [
        ("SPAN",           (0, 0), (1, 0)),
        ("BACKGROUND",     (0, 0), (-1, -1), colors.white),
        ("BOX",            (0, 0), (-1, -1), 0.4, _EJ_LINE),
        ("LINEBELOW",      (0, 0), (-1, 0), 1.0, _EJ_GOLD),
        ("LEFTPADDING",    (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",   (0, 0), (-1, -1), 8),
        ("TOPPADDING",     (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 4),
    ]
    marks = (rule_above,) if isinstance(rule_above, int) else tuple(rule_above)
    for mark in marks:
        if 0 <= mark < len(rows):
            r = mark + 1            # +1 for the header row
            style.append(("LINEABOVE", (0, r), (-1, r), 0.6, _EJ_BRAND))
    t.setStyle(TableStyle(style))
    return t


def _currency_bar(text: str, width: float = 180 * mm):
    t = Table([[Paragraph(f"<b>{_safe(text)}</b>", ParagraphStyle(
        "ccy_bar", fontName=_FONT_BOLD, fontSize=12, leading=14,
        textColor=_EJ_BRAND, alignment=TA_LEFT,
    ))]], colWidths=[width])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), _EJ_BRAND_3),
        ("LINEBELOW",     (0, 0), (-1, -1), 1.5, _EJ_GOLD),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


# Heading + emerald column header + one body row, with the leading gap.
# Deliberately small: this reserves a foothold, it does not try to hold a
# whole table together. A section that cannot fit even this much genuinely
# belongs on the next page.
_SECTION_FOOTHOLD = 22 * mm


def _titled_grid(title_flowable, table_flowable) -> List[Any]:
    """A section heading and its table, never separated by a page break.

    Returns the two flowables preceded by a conditional break, so the heading
    is only printed where at least the head of its table can follow it. A
    heading standing alone at the foot of a page reads as a section with
    nothing in it -- and the sections this guards ("Ledger", "Unapplied
    payments", the exposure tables) are precisely the ones where "nothing in
    it" is a claim about money.
    """
    return [CondPageBreak(_SECTION_FOOTHOLD), title_flowable, table_flowable]


def _grid_table(headers: List[str], rows: List[List[str]],
                col_widths: List[float], *, right_from: int,
                right_to: Optional[int] = None,
                shade_rows=(), font_size: int = 8):
    """Emerald-header data grid; columns in [*right_from*, *right_to*) are
    right-aligned, the rest left.

    The numeric band is a RANGE, not an open tail, because the detailed
    ledger ends on a text column (Status). Right-aligning a word against the
    money columns makes a wrapped label ("Due Date Unavailable") break with a
    ragged left edge and read as if it belonged to the amount beside it.

    *shade_rows* are 0-based body-row indexes to tint -- used to mark a row
    an aggregator warning already flagged, never to imply one. *font_size*
    exists so a wider grid can be set one point smaller instead of wrapping
    its own headers; padding follows it so the row height stays proportional.
    """
    pad = 4 if font_size >= 8 else 3
    hi = len(headers) if right_to is None else right_to

    def _right(i: int) -> bool:
        return right_from <= i < hi

    head = [
        Paragraph(f"<b>{_safe(h)}</b>", ParagraphStyle(
            "gh", fontName=_FONT_BOLD, fontSize=font_size,
            leading=font_size + 2, textColor=colors.white,
            alignment=TA_RIGHT if _right(i) else TA_LEFT,
        ))
        for i, h in enumerate(headers)
    ]
    t = Table([head] + [
        [
            Paragraph(_safe(c), ParagraphStyle(
                "gc", fontName=_FONT_REG, fontSize=font_size,
                leading=font_size + 2,
                alignment=TA_RIGHT if _right(i) else TA_LEFT,
            ))
            for i, c in enumerate(r)
        ]
        for r in rows
    ], colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), _EJ_BRAND),
        ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
        ("FONTNAME",      (0, 0), (-1, 0), _FONT_BOLD),
        ("FONTNAME",      (0, 1), (-1, -1), _FONT_REG),
        ("FONTSIZE",      (0, 0), (-1, -1), font_size),
        ("ALIGN",         (right_from, 0), (hi - 1, -1), "RIGHT"),
        ("LEFTPADDING",   (0, 0), (-1, -1), pad),
        ("RIGHTPADDING",  (0, 0), (-1, -1), pad),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW",     (0, 0), (-1, 0), 0.4, _EJ_GOLD),
        ("LINEBELOW",     (0, 1), (-1, -1), 0.3, _EJ_LINE),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ] + [("BACKGROUND", (0, r + 1), (-1, r + 1), _EJ_CREAM)
         for r in shade_rows]))
    return t


# The AP-local per-currency renderer that used to sit here is gone.
# Two copies meant two designs; `_currency_section_flowables(...,
# side="ap")` is now the only one.


def render_supplier_statement_pdf(
    statement: Dict[str, Any],
    *,
    seller: Optional[Dict[str, str]] = None,
    logo_path: str = "",
    document: str = "soa",
) -> bytes:
    """Render the ``aggregate_supplier_statement`` dict to PDF bytes.

    Business-facing by construction: no wFirma ids, no NBP / FX labels, no
    operator warnings, no query stats. Every figure is a string taken from the
    same statement dict the Supplier Ledger screen renders — this function
    performs no accounting arithmetic at all.

    *document* selects the same four products the receivable side offers, off
    the same shared section builder — there is one per-currency design in this
    module, parameterised by side, not two that drift.
    """
    if not isinstance(statement, dict):
        raise ValueError(
            "statement must be a dict produced by aggregate_supplier_statement"
        )
    title = statement_title("ap", document, statement)
    stmt = _strip_forbidden(statement)
    styles = _styles()
    seller = seller or {}

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=18 * mm, bottomMargin=15 * mm,
        title=title,
        author=(seller.get("name") or "Estrella Jewels"),
    )

    story: List[Any] = [
        _masthead_flowable(stmt, styles, seller=seller,
                           logo_path=logo_path or "", title=title),
        Spacer(1, 4),
        _meta_strip_flowable(stmt, styles),
        Spacer(1, 6),
        _customer_block_flowable(stmt, styles, customer_facing=True,
                                 label="Supplier"),
        Spacer(1, 8),
    ]
    story.extend(_period_integrity_flowables(stmt, styles, document=document))
    for ccy in (stmt.get("currencies") or []):
        story.extend(_currency_section_flowables(
            stmt, ccy, styles, side="ap", document=document,
        ))
    story.extend(_empty_notice_flowables(stmt, styles, side="ap"))

    if doc_cfg(document)["confirm"]:
        story.extend(_confirmation_flowables(stmt, styles, side="ap"))

    try:
        footer = _make_footer_drawer(stmt, seller=seller)
        doc.build(
            story, onFirstPage=footer, onLaterPages=footer,
            canvasmaker=_NumberedCanvas,
        )
    except Exception as exc:
        raise RuntimeError(f"reportlab build failed: {exc}") from exc

    pdf_bytes = buf.getvalue()
    if not pdf_bytes.startswith(b"%PDF-"):
        raise RuntimeError("reportlab produced output that does not look like a PDF")
    return pdf_bytes


# ── Management Analysis ───────────────────────────────────────────────────

def _scope_line(ar: Dict[str, Any]) -> str:
    """One sentence describing exactly which population the report covers.

    All-outstanding is a balance-sheet-style exposure with a configured
    lookback floor, so the floor is printed: open items issued before it sit
    outside this report, and that boundary must never be invisible.
    """
    f = ar.get("filters") or {}
    period = ar.get("period") or {}
    if (f.get("scope") or "") == "all_outstanding":
        floor = f.get("outstanding_floor") or period.get("from") or ""
        return f"All outstanding since {floor} · as of {ar.get('as_of') or ''}"
    return f"Period {period.get('from') or ''} → {period.get('to') or ''}"


def _ma_meta_strip(ar: Dict[str, Any], styles):
    f = ar.get("filters") or {}
    cells = [
        ("Report date", ar.get("generated_at") or ""),
        ("As of",       ar.get("as_of") or ""),
        ("Scope",       _scope_line(ar)),
        ("Filters",     " · ".join(p for p in (
            f"currency {f.get('currency')}" if f.get("currency") else "",
            f"AR {f.get('status')}" if f.get("status") else "",
        ) if p) or "none"),
    ]
    rows = [
        [Paragraph(_safe(lbl), styles["label"]) for lbl, _ in cells],
        [Paragraph(f"<b>{_safe(val)}</b>", styles["value"]) for _, val in cells],
    ]
    t = Table(rows, colWidths=[38 * mm, 30 * mm, 72 * mm, 40 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), _EJ_CREAM),
        ("BOX",           (0, 0), (-1, -1), 0.4, _EJ_LINE),
        ("INNERGRID",     (0, 0), (-1, -1), 0.4, _EJ_LINE),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def _exposure_flowables(title: str, headers, rows, col_widths, styles,
                        *, total_rows: int) -> List[Any]:
    head = Paragraph(f"<b>{_safe(title)}</b>", styles["section_header"])
    if not rows:
        return [head,
                Paragraph("<i>None in this currency.</i>", styles["subtle"])]
    out = _titled_grid(head, _grid_table(headers, rows, col_widths,
                                         right_from=1))
    if total_rows > len(rows):
        out.append(Paragraph(
            f"<i>Showing the {len(rows)} largest of {total_rows}. "
            f"The currency totals above cover all {total_rows}.</i>",
            styles["subtle"],
        ))
    return out


def _ma_currency_flowables(ccy: str, ar_sum, ap_sum, ar_rows, ap_rows,
                           styles) -> List[Any]:
    """One currency = one self-contained section. Currencies are never added
    together anywhere in this report."""
    out: List[Any] = [_currency_bar(f"Currency · {ccy}"), Spacer(1, 4)]

    ar_sum = ar_sum or {}
    ap_sum = ap_sum or {}
    # Same vocabulary as the per-counterparty position card: the splits
    # belong to gross, and the rule separates them from credits then net.
    recv_rows = [
        ("Gross receivable",     str(ar_sum.get("total_receivable") or "0.00")),
        ("of which overdue",     str(ar_sum.get("overdue") or "0.00")),
        ("of which not yet due", str(ar_sum.get("not_due") or "0.00")),
    ]
    # Neither overdue nor not-due: without this line the split above does
    # not add up to the gross figure. Printed only when it exists, which is
    # what the per-counterparty aging card already does.
    if ar_sum.get("due_date_unavailable") not in (None, "", "0.00"):
        recv_rows.append(
            ("of which no due date", str(ar_sum.get("due_date_unavailable"))),
        )
    recv_card = _kv_card("Receivables", recv_rows + [
        ("Customer credits", str(ar_sum.get("customer_credits") or "0.00")),
        ("Net receivable",   str(ar_sum.get("net_position") or "0.00")),
        ("Customers open",   str(ar_sum.get("customers_outstanding") or 0)),
        ("Oldest overdue",   f"{ar_sum.get('oldest_overdue_days') or 0} days"),
    ], styles, rule_above=(len(recv_rows), len(recv_rows) + 1))
    pay_rows = [
        ("Gross payable",        str(ap_sum.get("gross_payable") or "0.00")),
        ("of which overdue",     str(ap_sum.get("overdue") or "0.00")),
        ("of which not yet due", str(ap_sum.get("not_due") or "0.00")),
    ]
    if ap_sum.get("due_date_unavailable") not in (None, "", "0.00"):
        pay_rows.append(
            ("of which no due date", str(ap_sum.get("due_date_unavailable"))),
        )
    pay_card = _kv_card("Payables", pay_rows + [
        ("Supplier credits", str(ap_sum.get("supplier_credits") or "0.00")),
        ("Net payable",      str(ap_sum.get("net_payable") or "0.00")),
        ("Suppliers open",   str(ap_sum.get("suppliers_outstanding") or 0)),
    ], styles, rule_above=(len(pay_rows), len(pay_rows) + 1))
    cards = Table([[recv_card, pay_card]], colWidths=[90 * mm, 90 * mm])
    cards.setStyle(TableStyle([
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    out.append(cards)
    out.append(Spacer(1, 8))

    bucket_headers = [""] + [_BUCKET_LABELS[k] for k in _BUCKET_ORDER]
    def _bucket_row(label, src):
        return [label] + [_bucket_value(src or {}, k) for k in _BUCKET_ORDER]
    out.extend(_titled_grid(Paragraph(
        "<b>Aging · due date basis</b> "
        "<font size='7' color='#B0892F'>gross · before credits</font>",
        styles["section_header"]),
        _grid_table(
        bucket_headers,
        [_bucket_row("Receivables", ar_sum.get("aging")),
         _bucket_row("Payables", ap_sum.get("aging"))],
        [22 * mm, 20 * mm, 18 * mm, 18 * mm, 18 * mm, 20 * mm, 22 * mm, 18 * mm, 22 * mm],
        right_from=1,
        )))
    out.append(Spacer(1, 8))

    shown_ar = ar_rows[:_EXPOSURE_ROWS]
    out.extend(_exposure_flowables(
        "Customer exposure",
        ["Customer", "Gross receivable", "Overdue", "No due date",
         "Credits", "Oldest due", "Open"],
        [[r.get("customer_name") or "—", r.get("outstanding") or "0.00",
          r.get("overdue") or "0.00",
          r.get("due_date_unavailable") or "0.00",
          r.get("credit_balance") or "0.00",
          r.get("oldest_due_date") or "—", str(r.get("open_invoice_count") or 0)]
         for r in shown_ar],
        [46 * mm, 26 * mm, 24 * mm, 22 * mm, 22 * mm, 24 * mm, 16 * mm],
        styles, total_rows=len(ar_rows),
    ))
    out.append(Spacer(1, 8))

    shown_ap = ap_rows[:_EXPOSURE_ROWS]
    out.extend(_exposure_flowables(
        "Supplier exposure",
        ["Supplier", "Gross payable", "Overdue", "No due date",
         "Credits", "Oldest due", "Open"],
        [[r.get("supplier_name") or "—", r.get("gross_payable") or "0.00",
          r.get("overdue") or "0.00",
          r.get("due_date_unavailable") or "0.00",
          r.get("credit_balance") or "0.00",
          r.get("oldest_due_date") or "—", str(r.get("open_expense_count") or 0)]
         for r in shown_ap],
        [46 * mm, 26 * mm, 24 * mm, 22 * mm, 22 * mm, 24 * mm, 16 * mm],
        styles, total_rows=len(ap_rows),
    ))
    out.append(Spacer(1, 10))
    return out


def _appendix_flowables(ar: Dict[str, Any], ap: Dict[str, Any], styles) -> List[Any]:
    """Restrained data-quality appendix: how complete the underlying data is,
    so the figures above can be read with the right confidence."""
    arc = (ar.get("due_date_coverage") or {}).get("open_coverage_pct")
    apc = (ap.get("due_date_coverage") or {}).get("open_coverage_pct")
    ar_ok = bool((ar.get("source_health") or {}).get("ok", True))
    ap_ok = bool((ap.get("source_health") or {}).get("ok", True))
    lines = [
        f"Receivables — due dates present on {arc if arc is not None else '—'}% "
        f"of open invoices; source {'complete' if ar_ok else 'incomplete'}.",
        f"Payables — payment dates present on {apc if apc is not None else '—'}% "
        f"of open expenses; source {'complete' if ap_ok else 'incomplete'}.",
        "Amounts without a due date are reported under “Due n/a” and are "
        "included in the currency totals.",
    ]
    return [
        Spacer(1, 6),
        Paragraph("<b>Data quality</b>", styles["section_header"]),
    ] + [Paragraph(_safe(t), styles["subtle"]) for t in lines]


def render_management_analysis_pdf(
    ar: Dict[str, Any],
    ap: Dict[str, Any],
    *,
    seller: Optional[Dict[str, str]] = None,
    logo_path: str = "",
) -> bytes:
    """Render the management analysis (AR) + payables analysis (AP) dicts.

    Both arguments are the exact bodies the JSON routes return and the
    Management Analysis screen renders. This function selects and lays out;
    it never recomputes a balance and never adds two currencies together.
    """
    if not isinstance(ar, dict) or not isinstance(ap, dict):
        raise ValueError("ar and ap must be the analytics dicts")
    ar = _strip_forbidden(ar)
    ap = _strip_forbidden(ap)
    styles = _styles()
    seller = seller or {}

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=18 * mm, bottomMargin=15 * mm,
        title="Management Analysis",
        author=(seller.get("name") or "Estrella Jewels"),
    )

    ar_sums = {s.get("currency"): s for s in (ar.get("currency_summaries") or [])}
    ap_sums = {s.get("currency"): s for s in (ap.get("currency_summaries") or [])}
    currencies = sorted(set(ar_sums) | set(ap_sums))

    story: List[Any] = [
        _masthead_flowable({}, styles, seller=seller, logo_path=logo_path or "",
                           title="Management Analysis"),
        Spacer(1, 4),
        _ma_meta_strip(ar, styles),
        Spacer(1, 8),
    ]
    for i, ccy in enumerate(currencies):
        if i:
            story.append(PageBreak())
        story.extend(_ma_currency_flowables(
            ccy, ar_sums.get(ccy), ap_sums.get(ccy),
            [r for r in (ar.get("customers") or []) if r.get("currency") == ccy],
            [r for r in (ap.get("suppliers") or []) if r.get("currency") == ccy],
            styles,
        ))
    if not currencies:
        story.append(Spacer(1, 12))
        story.append(Paragraph(
            "<i>No open receivables or payables in this scope.</i>",
            styles["subtle"],
        ))
    story.extend(_appendix_flowables(ar, ap, styles))

    # Footer: aging basis is due date on both sides of this report.
    footer_ctx = {"generated_at": ar.get("generated_at") or "",
                  "aging_method": "due_date"}
    try:
        footer = _make_footer_drawer(footer_ctx, seller=seller)
        doc.build(
            story, onFirstPage=footer, onLaterPages=footer,
            canvasmaker=_NumberedCanvas,
        )
    except Exception as exc:
        raise RuntimeError(f"reportlab build failed: {exc}") from exc

    pdf_bytes = buf.getvalue()
    if not pdf_bytes.startswith(b"%PDF-"):
        raise RuntimeError("reportlab produced output that does not look like a PDF")
    return pdf_bytes


def render_treasury_balances_pdf(
    payload: Dict[str, Any],
    *,
    seller: Optional[Dict[str, str]] = None,
    logo_path: str = "",
) -> bytes:
    """Render GET /treasury/balances JSON. No monetary arithmetic."""
    if not isinstance(payload, dict):
        raise ValueError("treasury payload must be a dict")
    stmt = _strip_forbidden(payload)
    styles = _styles()
    seller = seller or {}
    as_of = str(stmt.get("as_of") or "")
    meta = {
        "generated_at": stmt.get("generated_at") or as_of,
        "as_of": as_of,
        "period": {"from": as_of, "to": as_of},
        "currencies": sorted({
            str(r.get("currency") or "")
            for r in (stmt.get("rows") or [])
            if r.get("currency")
        }),
        "source": stmt.get("source") or "treasury.sqlite",
        "freshness": stmt.get("freshness") or "as_of_snapshot",
        "reconciliation_status": stmt.get("authority") or "local_treasury_projection",
        "aging_method": "due_date",
        "contractor": {"name": "Treasury balances"},
    }

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=18 * mm, bottomMargin=15 * mm,
        title="Treasury Balances",
        author=(seller.get("name") or "Estrella Jewels"),
    )
    story: List[Any] = [
        _masthead_flowable(meta, styles, seller=seller,
                           logo_path=logo_path or "", title="Treasury Balances"),
        Spacer(1, 4),
        _meta_strip_flowable(meta, styles),
        Spacer(1, 8),
    ]
    rows = stmt.get("rows") or []
    if not rows:
        story.append(Paragraph(
            "<i>No treasury snapshots for this as-of date.</i>",
            styles["subtle"],
        ))
    else:
        grid = []
        for r in rows:
            grid.append([
                str(r.get("account_location") or ""),
                str(r.get("currency") or ""),
                str(r.get("closing_balance") or "0.00"),
                str(r.get("source") or ""),
                str(r.get("effective_date") or ""),
                str(r.get("operator") or ""),
            ])
        story.append(_grid_table(
            ["Account", "Ccy", "Closing", "Source", "Effective", "Operator"],
            grid,
            [42 * mm, 16 * mm, 28 * mm, 28 * mm, 28 * mm, 38 * mm],
            right_from=2,
        ))
    try:
        footer = _make_footer_drawer(meta, seller=seller)
        doc.build(
            story, onFirstPage=footer, onLaterPages=footer,
            canvasmaker=_NumberedCanvas,
        )
    except Exception as exc:
        raise RuntimeError(f"reportlab build failed: {exc}") from exc
    pdf_bytes = buf.getvalue()
    if not pdf_bytes.startswith(b"%PDF-"):
        raise RuntimeError("reportlab produced output that does not look like a PDF")
    return pdf_bytes


__all__ = [
    "render_statement_pdf",
    "render_supplier_statement_pdf",
    "render_management_analysis_pdf",
    "render_treasury_balances_pdf",
]
