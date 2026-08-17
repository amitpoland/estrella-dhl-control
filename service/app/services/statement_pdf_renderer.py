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
from reportlab.platypus import (
    KeepTogether, PageBreak, Paragraph, SimpleDocTemplate,
    Spacer, Table, TableStyle, Image,
)


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
        ("/Library/Fonts/DejaVuSans.ttf",
         "/Library/Fonts/DejaVuSans-Bold.ttf"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
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
    """Four-column metadata strip: Issued / Period / Aging method / Currencies."""
    period_str = f"{stmt['period']['from']} → {stmt['period']['to']}"
    currencies = ", ".join(stmt.get("currencies") or []) or "—"
    # Aging method label drawn from the FIRST currency block (all
    # blocks share the same hardcoded label in Phase 10B). Fall back
    # to the "Invoice age" literal when there's no aging block.
    aging_blocks = stmt.get("aging_per_currency") or {}
    method_token = stmt.get("aging_method") or "due_date"
    for v in aging_blocks.values():
        method_token = v.get("method", method_token) or method_token
        break
    method_label = _aging_method_label(method_token)

    cells = [
        ("Issued",         _safe(stmt.get("generated_at") or "")),
        ("Period",         _safe(period_str)),
        ("Aging method",   _safe(method_label)),
        ("Currencies",     _safe(currencies)),
    ]
    rows = [
        [Paragraph(label, styles["label"]) for label, _ in cells],
        [Paragraph(f"<b>{val}</b>", styles["value"]) for _, val in cells],
    ]
    t = Table(rows, colWidths=[45*mm]*4)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), _EJ_CREAM),
        ("BOX",           (0,0), (-1,-1), 0.4, _EJ_LINE),
        ("INNERGRID",     (0,0), (-1,-1), 0.4, _EJ_LINE),
        ("VALIGN",        (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING",   (0,0), (-1,-1), 8),
        ("RIGHTPADDING",  (0,0), (-1,-1), 8),
        ("TOPPADDING",    (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
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


def _currency_section_flowables(
    stmt: Dict[str, Any],
    ccy:  str,
    styles,
) -> List[Any]:
    """Build the per-currency block: header, totals card + aging card,
    ledger table, optional unmatched-payments mini-table."""
    out: List[Any] = []

    # Currency header.
    header = Table(
        [[Paragraph(f"<b>Currency · {ccy}</b>", ParagraphStyle(
            "ccy_header", fontName=_FONT_BOLD, fontSize=12,
            leading=14, textColor=_EJ_BRAND, alignment=TA_LEFT,
        ))]],
        colWidths=[180*mm],
    )
    header.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), _EJ_BRAND_3),
        ("LINEBELOW",     (0,0), (-1,-1), 1.5, _EJ_GOLD),
        ("LEFTPADDING",   (0,0), (-1,-1), 8),
        ("TOPPADDING",    (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ]))

    totals = (stmt.get("totals_per_currency") or {}).get(ccy) or {}
    aging  = (stmt.get("aging_per_currency")  or {}).get(ccy) or {}

    # Totals card.
    out_amt = _safe(totals.get("outstanding") or "0.00")
    is_negative = False
    try:
        is_negative = Decimal(str(totals.get("outstanding") or "0")) < 0
    except Exception:
        is_negative = False
    out_color = "#B91C1C" if is_negative else "#0B3D2E"
    totals_rows = [
        ["Invoiced",     _safe(totals.get("invoiced")     or "0.00")],
        ["Credited",     _safe(totals.get("credited")     or "0.00")],
        ["Received",     _safe(totals.get("received")     or "0.00")],
        ["Outstanding",  out_amt],
        ["Entries",      str(totals.get("entry_count")   or 0)],
    ]
    totals_t = Table(
        [[Paragraph("<b>Totals</b>", styles["section_header"])]] + [
            [Paragraph(f"<font color='#475569'>{lbl}</font>",
                        ParagraphStyle("tk", fontName=_FONT_REG, fontSize=9,
                                        leading=11, alignment=TA_LEFT)),
             Paragraph(f"<font name='{_FONT_BOLD}' "
                        f"color='{out_color if lbl == 'Outstanding' else '#0F172A'}'>"
                        f"{val}</font>",
                        ParagraphStyle("tv", fontName=_FONT_BOLD, fontSize=10,
                                        leading=12, alignment=TA_RIGHT))]
            for lbl, val in totals_rows
        ],
        colWidths=[40*mm, 45*mm],
    )
    totals_t.setStyle(TableStyle([
        ("SPAN",           (0,0), (1,0)),
        ("BACKGROUND",     (0,0), (-1,-1), colors.white),
        ("BOX",            (0,0), (-1,-1), 0.4, _EJ_LINE),
        ("LINEBELOW",      (0,0), (-1,0),  1.0, _EJ_GOLD),
        ("LINEABOVE",      (0,4), (-1,4),  0.6, _EJ_BRAND),  # over Outstanding
        ("LEFTPADDING",    (0,0), (-1,-1), 8),
        ("RIGHTPADDING",   (0,0), (-1,-1), 8),
        ("TOPPADDING",     (0,0), (-1,-1), 4),
        ("BOTTOMPADDING",  (0,0), (-1,-1), 4),
    ]))

    # Aging card — canonical financial_aging keys (MA / statement parity).
    method = _aging_method_label(aging.get("method") or "due_date")
    aging_rows = [
        ["not due",  _safe(aging.get("not_due") or aging.get("current") or "0.00")],
        ["1–30",     _safe(aging.get("b_1_30") or aging.get("1_30") or "0.00")],
        ["31–60",    _safe(aging.get("b_31_60") or aging.get("31_60") or "0.00")],
        ["61–90",    _safe(aging.get("b_61_90") or aging.get("61_90") or "0.00")],
        ["91–180",   _safe(aging.get("b_91_180") or "0.00")],
        ["181–365",  _safe(aging.get("b_181_365") or "0.00")],
        ["365+",     _safe(aging.get("b_365_plus") or aging.get("90_plus") or "0.00")],
    ]
    if aging.get("due_date_unavailable") not in (None, "", "0.00"):
        aging_rows.append([
            "due date n/a",
            _safe(aging.get("due_date_unavailable") or "0.00"),
        ])
    aging_rows.append(["total", _safe(aging.get("total") or "0.00")])
    aging_t = Table(
        [[Paragraph(f"<b>Aging</b><br/>"
                     f"<font size='7' color='#B0892F'>method · {method}</font>",
                     styles["section_header"])]] + [
            [Paragraph(f"<font color='#475569'>{lbl}</font>",
                        ParagraphStyle("ak", fontName=_FONT_REG, fontSize=9,
                                        leading=11, alignment=TA_LEFT)),
             Paragraph(f"<font name='{_FONT_BOLD}'>{val}</font>",
                        ParagraphStyle("av", fontName=_FONT_BOLD, fontSize=10,
                                        leading=12, alignment=TA_RIGHT))]
            for lbl, val in aging_rows
        ],
        colWidths=[40*mm, 45*mm],
    )
    aging_t.setStyle(TableStyle([
        ("SPAN",           (0,0), (1,0)),
        ("BACKGROUND",     (0,0), (-1,-1), colors.white),
        ("BOX",            (0,0), (-1,-1), 0.4, _EJ_LINE),
        ("LINEBELOW",      (0,0), (-1,0),  1.0, _EJ_GOLD),
        ("LINEABOVE",      (0,6), (-1,6),  0.6, _EJ_BRAND),  # over total
        ("LEFTPADDING",    (0,0), (-1,-1), 8),
        ("RIGHTPADDING",   (0,0), (-1,-1), 8),
        ("TOPPADDING",     (0,0), (-1,-1), 4),
        ("BOTTOMPADDING",  (0,0), (-1,-1), 4),
    ]))

    cards_row = Table([[totals_t, aging_t]], colWidths=[90*mm, 90*mm])
    cards_row.setStyle(TableStyle([
        ("VALIGN",        (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING",   (0,0), (-1,-1), 0),
        ("RIGHTPADDING",  (0,0), (-1,-1), 0),
    ]))

    out.append(KeepTogether([header, Spacer(1, 4), cards_row]))
    out.append(Spacer(1, 6))

    # Ledger table.
    entries = (stmt.get("entries_per_currency") or {}).get(ccy) or []
    out.append(Paragraph("<b>Ledger</b>", styles["section_header"]))

    table_data = [[
        Paragraph("<b>Date</b>",     ParagraphStyle("th", fontName=_FONT_BOLD, fontSize=8, textColor=colors.white)),
        Paragraph("<b>Type</b>",     ParagraphStyle("th", fontName=_FONT_BOLD, fontSize=8, textColor=colors.white)),
        Paragraph("<b>Doc</b>",      ParagraphStyle("th", fontName=_FONT_BOLD, fontSize=8, textColor=colors.white)),
        Paragraph("<b>Linked</b>",   ParagraphStyle("th", fontName=_FONT_BOLD, fontSize=8, textColor=colors.white)),
        Paragraph("<b>Debit</b>",    ParagraphStyle("th", fontName=_FONT_BOLD, fontSize=8, textColor=colors.white, alignment=TA_RIGHT)),
        Paragraph("<b>Credit</b>",   ParagraphStyle("th", fontName=_FONT_BOLD, fontSize=8, textColor=colors.white, alignment=TA_RIGHT)),
        Paragraph("<b>Balance</b>",  ParagraphStyle("th", fontName=_FONT_BOLD, fontSize=8, textColor=colors.white, alignment=TA_RIGHT)),
    ]]
    overpaid_ids = {
        w.get("wfirma_doc_id")
        for w in (stmt.get("warnings") or [])
        if w.get("event") == "overpayment_on_invoice"
    }
    body_styles = TableStyle([
        ("FONTNAME",       (0,0), (-1,0), _FONT_BOLD),
        ("BACKGROUND",     (0,0), (-1,0), _EJ_BRAND),
        ("TEXTCOLOR",      (0,0), (-1,0), colors.white),
        ("ALIGN",          (4,0), (-1,-1), "RIGHT"),
        ("FONTNAME",       (0,1), (-1,-1), _FONT_REG),
        ("FONTSIZE",       (0,0), (-1,-1), 8),
        ("LEFTPADDING",    (0,0), (-1,-1), 4),
        ("RIGHTPADDING",   (0,0), (-1,-1), 4),
        ("TOPPADDING",     (0,0), (-1,-1), 3),
        ("BOTTOMPADDING",  (0,0), (-1,-1), 3),
        ("LINEBELOW",      (0,0), (-1,0),  0.4, _EJ_GOLD),
        ("LINEBELOW",      (0,1), (-1,-1), 0.3, _EJ_LINE),
        ("VALIGN",         (0,0), (-1,-1), "MIDDLE"),
    ])
    for i, e in enumerate(entries, start=1):
        ent_type   = (e.get("type") or "").strip()
        doc_number = e.get("doc_number") or e.get("wfirma_doc_id") or ""
        linked     = e.get("linked_invoice") or ""
        debit      = e.get("debit")  or "0.00"
        credit     = e.get("credit") or "0.00"
        balance    = e.get("running_balance") or "0.00"

        # Type pill colour.
        type_color = {
            "invoice":    "#0B3D2E",
            "correction": "#B0892F",
            "proforma":   "#475569",
            "payment":    "#0F5A45",
        }.get(ent_type, "#475569")

        table_data.append([
            _safe(e.get("date") or ""),
            Paragraph(f"<font color='{type_color}'><b>{_safe(ent_type)}</b></font>",
                       ParagraphStyle("c", fontName=_FONT_BOLD, fontSize=8)),
            _safe(doc_number),
            _safe(linked),
            _safe(debit),
            _safe(credit),
            _safe(balance),
        ])
        # Overpayment highlight.
        if e.get("wfirma_doc_id") in overpaid_ids:
            body_styles.add("BACKGROUND", (0, i), (-1, i), _EJ_CREAM)

    ledger_t = Table(
        table_data,
        colWidths=[20*mm, 18*mm, 32*mm, 28*mm, 26*mm, 26*mm, 30*mm],
        repeatRows=1,
    )
    ledger_t.setStyle(body_styles)
    out.append(ledger_t)

    if not entries:
        out.append(Paragraph(
            "<i>No entries in this currency for the selected period.</i>",
            styles["subtle"],
        ))

    # Unmatched payments mini-table for this currency, if any.
    unm = ((stmt.get("unmatched_payments_per_currency") or {})
           .get(ccy) or [])
    if unm:
        out.append(Spacer(1, 6))
        out.append(Paragraph(
            "<b><font color='#B91C1C'>Unmatched payments</font></b>",
            styles["section_header"],
        ))
        unm_data = [[
            Paragraph("<b>Date</b>",       ParagraphStyle("uh", fontName=_FONT_BOLD, fontSize=8, textColor=colors.white)),
            Paragraph("<b>Doc</b>",        ParagraphStyle("uh", fontName=_FONT_BOLD, fontSize=8, textColor=colors.white)),
            Paragraph("<b>Value</b>",      ParagraphStyle("uh", fontName=_FONT_BOLD, fontSize=8, textColor=colors.white, alignment=TA_RIGHT)),
            Paragraph("<b>Currency</b>",   ParagraphStyle("uh", fontName=_FONT_BOLD, fontSize=8, textColor=colors.white)),
            Paragraph("<b>Linked attempt</b>", ParagraphStyle("uh", fontName=_FONT_BOLD, fontSize=8, textColor=colors.white)),
        ]]
        for u in unm:
            unm_data.append([
                _safe(u.get("date") or ""),
                _safe(u.get("wfirma_doc_id") or ""),
                _safe(u.get("value") or "0.00"),
                _safe(u.get("currency") or ""),
                _safe(u.get("linked_invoice") or "—"),
            ])
        unm_t = Table(unm_data,
                      colWidths=[22*mm, 32*mm, 30*mm, 22*mm, 70*mm])
        unm_t.setStyle(TableStyle([
            ("BACKGROUND",     (0,0), (-1,0), _EJ_RED),
            ("TEXTCOLOR",      (0,0), (-1,0), colors.white),
            ("FONTNAME",       (0,0), (-1,0), _FONT_BOLD),
            ("FONTNAME",       (0,1), (-1,-1), _FONT_REG),
            ("FONTSIZE",       (0,0), (-1,-1), 8),
            ("ALIGN",          (2,0), (2,-1), "RIGHT"),
            ("LEFTPADDING",    (0,0), (-1,-1), 4),
            ("RIGHTPADDING",   (0,0), (-1,-1), 4),
            ("TOPPADDING",     (0,0), (-1,-1), 3),
            ("BOTTOMPADDING",  (0,0), (-1,-1), 3),
            ("BOX",            (0,0), (-1,-1), 0.4, _EJ_RED),
            ("LINEBELOW",      (0,1), (-1,-1), 0.2, _EJ_LINE),
            ("VALIGN",         (0,0), (-1,-1), "MIDDLE"),
        ]))
        out.append(unm_t)

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


def _empty_notice_flowables(stmt: Dict[str, Any], styles) -> List[Any]:
    if (stmt.get("currencies") or []):
        return []
    return [
        Spacer(1, 12),
        Paragraph(
            "<i>No invoices or payments for this contractor in the "
            "selected period.</i>",
            styles["subtle"],
        ),
    ]


# ── Page decorator (footer) ────────────────────────────────────────────────

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
    # Keep footer readable on A4.
    if len(left) > 78:
        left = left[:75] + "…"

    def _drawer(canvas, doc):
        canvas.saveState()
        canvas.setFont(_FONT_REG, 6.5)
        canvas.setFillColor(_EJ_INK_2)
        canvas.drawString(15*mm, 10*mm, left)
        page_str = f"Page {canvas.getPageNumber()}"
        canvas.drawCentredString(105*mm, 10*mm, page_str)
        canvas.setFont(_FONT_BOLD, 7)
        canvas.setFillColor(_EJ_GOLD_2)
        right = f"Aging: {method_label} · {generated_at}"
        canvas.drawRightString(195*mm, 10*mm, right)
        canvas.restoreState()
    return _drawer


# ── Public entry point ────────────────────────────────────────────────────

def render_statement_pdf(
    statement: Dict[str, Any],
    *,
    customer_facing: bool = True,
    seller: Optional[Dict[str, str]] = None,
    logo_path: str = "",
) -> bytes:
    """Render a Phase 10B Statement-of-Account dict to PDF bytes.

    Pure relative to ledger arithmetic: no wFirma / no re-aggregation.
    Optional *seller* / *logo_path* are presentation inputs supplied by
    the route from CompanyProfile + the shared document-suite asset.

    When *customer_facing* is True (default for the PDF route): omit
    wFirma contractor id and DQ / implementation warnings.
    """
    if not isinstance(statement, dict):
        raise ValueError("statement must be a dict produced by aggregate_statement")

    # Defence-in-depth: drop any forbidden keys before rendering.
    stmt = _strip_forbidden(statement)
    styles = _styles()
    seller = seller or {}

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=15*mm, rightMargin=15*mm,
        topMargin=18*mm,  bottomMargin=15*mm,
        title="Statement of Account",
        author=(seller.get("name") or "Estrella Jewels"),
    )

    story: List[Any] = []
    story.append(_masthead_flowable(
        stmt, styles, seller=seller, logo_path=logo_path or "",
    ))
    story.append(Spacer(1, 4))
    story.append(_meta_strip_flowable(stmt, styles))
    story.append(Spacer(1, 6))
    story.append(_customer_block_flowable(
        stmt, styles, customer_facing=customer_facing,
    ))
    story.append(Spacer(1, 8))

    for ccy in (stmt.get("currencies") or []):
        story.extend(_currency_section_flowables(stmt, ccy, styles))

    story.extend(_empty_notice_flowables(stmt, styles))

    # Customer PDF: DQ / operator warnings stay on JSON / internal UI only.
    if not customer_facing:
        story.extend(_warnings_flowables(stmt, styles))

    try:
        footer = _make_footer_drawer(stmt, seller=seller)
        doc.build(story, onFirstPage=footer, onLaterPages=footer)
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

# AP/MA aging buckets, in report order. Same keys as financial_aging
# (via accounting_analytics) so Supplier Statement / MA PDF cannot disagree.
_AP_BUCKETS: Tuple[Tuple[str, str], ...] = (
    ("not_due",              "Not due"),
    ("b_1_30",               "1–30"),
    ("b_31_60",              "31–60"),
    ("b_61_90",              "61–90"),
    ("b_91_180",             "91–180"),
    ("b_181_365",            "181–365"),
    ("b_365_plus",           "365+"),
    ("due_date_unavailable", "Due date n/a"),
)

# Exposure tables are capped so one currency cannot push the report to 200
# pages. The cap is printed whenever it bites — a silently truncated exposure
# table reads as "this is everyone", which is exactly the wrong conclusion.
_EXPOSURE_ROWS = 25


def _kv_card(title: str, rows: List[Tuple[str, str]], styles, *,
             rule_above: int = -1, width: float = 85 * mm):
    """Label/value card — the Totals and Aging cards are both this shape.

    *rule_above* draws the brand rule above that body row (0-based over
    *rows*), used to set a total apart from the lines that make it up.
    """
    data = [[Paragraph(f"<b>{_safe(title)}</b>", styles["section_header"]), ""]]
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
    if 0 <= rule_above < len(rows):
        r = rule_above + 1          # +1 for the header row
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


def _grid_table(headers: List[str], rows: List[List[str]],
                col_widths: List[float], *, right_from: int):
    """Emerald-header data grid; columns from *right_from* are right-aligned."""
    head = [
        Paragraph(f"<b>{_safe(h)}</b>", ParagraphStyle(
            "gh", fontName=_FONT_BOLD, fontSize=8, textColor=colors.white,
            alignment=TA_RIGHT if i >= right_from else TA_LEFT,
        ))
        for i, h in enumerate(headers)
    ]
    t = Table([head] + [[_safe(c) for c in r] for r in rows],
              colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0), _EJ_BRAND),
        ("TEXTCOLOR",     (0, 0), (-1, 0), colors.white),
        ("FONTNAME",      (0, 0), (-1, 0), _FONT_BOLD),
        ("FONTNAME",      (0, 1), (-1, -1), _FONT_REG),
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
        ("ALIGN",         (right_from, 0), (-1, -1), "RIGHT"),
        ("LEFTPADDING",   (0, 0), (-1, -1), 4),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW",     (0, 0), (-1, 0), 0.4, _EJ_GOLD),
        ("LINEBELOW",     (0, 1), (-1, -1), 0.3, _EJ_LINE),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return t


def _aging_rows(block: Dict[str, Any]) -> List[Tuple[str, str]]:
    """AP aging card rows — hide an empty ``due date n/a`` line, keep total."""
    rows: List[Tuple[str, str]] = []
    for key, label in _AP_BUCKETS:
        val = str(block.get(key) or "0.00")
        if key == "due_date_unavailable" and val in ("0.00", "0", ""):
            continue
        rows.append((label, val))
    rows.append(("Total", str(block.get("total") or "0.00")))
    return rows


def _supplier_currency_flowables(stmt: Dict[str, Any], ccy: str, styles) -> List[Any]:
    """Per-currency block of the Supplier Statement: totals + aging cards,
    then the chronological ledger."""
    out: List[Any] = []
    totals = (stmt.get("totals_per_currency") or {}).get(ccy) or {}
    aging = (stmt.get("aging_per_currency") or {}).get(ccy) or {}

    totals_card = _kv_card("Totals", [
        ("Expenses",         str(totals.get("gross_payable") or "0.00")),
        ("Supplier credits", str(totals.get("supplier_credits") or "0.00")),
        ("Payments applied", str(totals.get("payments_applied") or "0.00")),
        ("Outstanding",      str(totals.get("outstanding") or "0.00")),
        ("Net payable",      str(totals.get("net_payable") or "0.00")),
        ("Entries",          str(totals.get("entry_count") or 0)),
    ], styles, rule_above=3)
    aging_card = _kv_card("Aging · due date", _aging_rows(aging), styles,
                          rule_above=len(_aging_rows(aging)) - 1)

    cards = Table([[totals_card, aging_card]], colWidths=[90 * mm, 90 * mm])
    cards.setStyle(TableStyle([
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    out.append(KeepTogether([_currency_bar(f"Currency · {ccy}"), Spacer(1, 4), cards]))
    out.append(Spacer(1, 6))

    entries = (stmt.get("entries_per_currency") or {}).get(ccy) or []
    out.append(Paragraph("<b>Ledger</b>", styles["section_header"]))
    rows = []
    for e in entries:
        # Document number only — never the wFirma object id. A payment row
        # carries no supplier document number, so it prints as a dash.
        rows.append([
            e.get("date") or "",
            (e.get("type") or "").replace("_", " "),
            e.get("doc_number") or "—",
            e.get("due_date") or "—",
            e.get("debit") or "0.00",
            e.get("credit") or "0.00",
            e.get("running_balance") or "0.00",
        ])
    out.append(_grid_table(
        ["Date", "Type", "Document", "Due", "Expense", "Credit/Payment", "Balance"],
        rows, [20 * mm, 22 * mm, 32 * mm, 20 * mm, 26 * mm, 30 * mm, 30 * mm],
        right_from=4,
    ))
    if not entries:
        out.append(Paragraph(
            "<i>No entries in this currency for the selected period.</i>",
            styles["subtle"],
        ))
    out.append(Spacer(1, 8))
    return out


def render_supplier_statement_pdf(
    statement: Dict[str, Any],
    *,
    seller: Optional[Dict[str, str]] = None,
    logo_path: str = "",
) -> bytes:
    """Render the ``aggregate_supplier_statement`` dict to PDF bytes.

    Business-facing by construction: no wFirma ids, no NBP / FX labels, no
    operator warnings, no query stats. Every figure is a string taken from the
    same statement dict the Supplier Ledger screen renders — this function
    performs no accounting arithmetic at all.
    """
    if not isinstance(statement, dict):
        raise ValueError(
            "statement must be a dict produced by aggregate_supplier_statement"
        )
    stmt = _strip_forbidden(statement)
    styles = _styles()
    seller = seller or {}

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=18 * mm, bottomMargin=15 * mm,
        title="Supplier Statement",
        author=(seller.get("name") or "Estrella Jewels"),
    )

    story: List[Any] = [
        _masthead_flowable(stmt, styles, seller=seller,
                           logo_path=logo_path or "", title="Supplier Statement"),
        Spacer(1, 4),
        _meta_strip_flowable(stmt, styles),
        Spacer(1, 6),
        _customer_block_flowable(stmt, styles, customer_facing=True,
                                 label="Supplier"),
        Spacer(1, 8),
    ]
    for ccy in (stmt.get("currencies") or []):
        story.extend(_supplier_currency_flowables(stmt, ccy, styles))
    if not (stmt.get("currencies") or []):
        story.append(Spacer(1, 12))
        story.append(Paragraph(
            "<i>No expenses or payments for this supplier in the selected "
            "period.</i>", styles["subtle"],
        ))

    try:
        footer = _make_footer_drawer(stmt, seller=seller)
        doc.build(story, onFirstPage=footer, onLaterPages=footer)
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
    out = [Paragraph(f"<b>{_safe(title)}</b>", styles["section_header"])]
    if not rows:
        out.append(Paragraph("<i>None in this currency.</i>", styles["subtle"]))
        return out
    out.append(_grid_table(headers, rows, col_widths, right_from=1))
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
    recv_card = _kv_card("Receivables", [
        ("Total receivable", str(ar_sum.get("total_receivable") or "0.00")),
        ("Overdue",          str(ar_sum.get("overdue") or "0.00")),
        ("Not due",          str(ar_sum.get("not_due") or "0.00")),
        ("Customer credits", str(ar_sum.get("customer_credits") or "0.00")),
        ("Customers open",   str(ar_sum.get("customers_outstanding") or 0)),
        ("Oldest overdue",   f"{ar_sum.get('oldest_overdue_days') or 0} days"),
    ], styles, rule_above=0)
    pay_card = _kv_card("Payables", [
        ("Gross payable",    str(ap_sum.get("gross_payable") or "0.00")),
        ("Overdue",          str(ap_sum.get("overdue") or "0.00")),
        ("Not due",          str(ap_sum.get("not_due") or "0.00")),
        ("Supplier credits", str(ap_sum.get("supplier_credits") or "0.00")),
        ("Net payable",      str(ap_sum.get("net_payable") or "0.00")),
        ("Suppliers open",   str(ap_sum.get("suppliers_outstanding") or 0)),
    ], styles, rule_above=0)
    cards = Table([[recv_card, pay_card]], colWidths=[90 * mm, 90 * mm])
    cards.setStyle(TableStyle([
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    out.append(cards)
    out.append(Spacer(1, 8))

    bucket_headers = ["", "Not due", "1–30", "31–60", "61–90", "91–180", "181–365", "365+", "Due n/a"]
    def _bucket_row(label, src):
        return [label] + [str((src or {}).get(k) or "0.00")
                          for k, _ in _AP_BUCKETS]
    out.append(Paragraph("<b>Aging · due date basis</b>", styles["section_header"]))
    out.append(_grid_table(
        bucket_headers,
        [_bucket_row("Receivables", ar_sum.get("aging")),
         _bucket_row("Payables", ap_sum.get("aging"))],
        [22 * mm, 20 * mm, 18 * mm, 18 * mm, 18 * mm, 20 * mm, 22 * mm, 18 * mm, 22 * mm],
        right_from=1,
    ))
    out.append(Spacer(1, 8))

    shown_ar = ar_rows[:_EXPOSURE_ROWS]
    out.extend(_exposure_flowables(
        "Customer exposure",
        ["Customer", "Outstanding", "Overdue", "Credits", "Oldest due", "Open"],
        [[r.get("customer_name") or "—", r.get("outstanding") or "0.00",
          r.get("overdue") or "0.00", r.get("credit_balance") or "0.00",
          r.get("oldest_due_date") or "—", str(r.get("open_invoice_count") or 0)]
         for r in shown_ar],
        [58 * mm, 28 * mm, 28 * mm, 26 * mm, 24 * mm, 16 * mm],
        styles, total_rows=len(ar_rows),
    ))
    out.append(Spacer(1, 8))

    shown_ap = ap_rows[:_EXPOSURE_ROWS]
    out.extend(_exposure_flowables(
        "Supplier exposure",
        ["Supplier", "Gross payable", "Overdue", "Credits", "Oldest due", "Open"],
        [[r.get("supplier_name") or "—", r.get("gross_payable") or "0.00",
          r.get("overdue") or "0.00", r.get("credit_balance") or "0.00",
          r.get("oldest_due_date") or "—", str(r.get("open_expense_count") or 0)]
         for r in shown_ap],
        [58 * mm, 28 * mm, 28 * mm, 26 * mm, 24 * mm, 16 * mm],
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
        doc.build(story, onFirstPage=footer, onLaterPages=footer)
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
]
