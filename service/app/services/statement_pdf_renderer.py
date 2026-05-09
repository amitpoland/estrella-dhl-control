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
    Spacer, Table, TableStyle,
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
    return "Invoice age"   # default + explicit pin per Phase 10B/C contract


# ── Section builders ───────────────────────────────────────────────────────

def _masthead_flowable(stmt: Dict[str, Any], styles: Dict[str, ParagraphStyle]):
    """Emerald-to-gold band with EJ logo mark + Statement of Account
    title. Single-row Table so KeepTogether keeps it intact."""
    eyebrow = "ESTRELLA JEWELS · DOCUMENT SUITE"
    title   = "Statement of Account"

    # Logo "mark": gold-on-emerald square with EJ initials.
    mark = Table(
        [[Paragraph("<b>EJ</b>", ParagraphStyle(
            "logo_mark", fontName=_FONT_BOLD, fontSize=14,
            leading=16, textColor=_EJ_GOLD, alignment=TA_CENTER,
        ))]],
        colWidths=[10*mm], rowHeights=[10*mm],
    )
    mark.setStyle(TableStyle([
        ("BACKGROUND",   (0,0), (-1,-1), _EJ_BRAND_2),
        ("BOX",          (0,0), (-1,-1), 1.2, _EJ_GOLD_TINT),
        ("VALIGN",       (0,0), (-1,-1), "MIDDLE"),
        ("ALIGN",        (0,0), (-1,-1), "CENTER"),
    ]))

    text_block = [
        Paragraph(eyebrow, styles["eyebrow"]),
        Paragraph(title,   styles["title"]),
    ]

    band = Table(
        [[mark, text_block]],
        colWidths=[14*mm, 166*mm],
    )
    band.setStyle(TableStyle([
        ("BACKGROUND",     (0,0), (0,0),   _EJ_BRAND),
        # Right cell: emerald with a gold strip on the right edge.
        ("BACKGROUND",     (1,0), (1,0),   _EJ_BRAND),
        ("LINEAFTER",      (1,0), (1,0),   3, _EJ_GOLD),
        ("VALIGN",         (0,0), (-1,-1), "MIDDLE"),
        ("LEFTPADDING",    (0,0), (-1,-1), 8),
        ("RIGHTPADDING",   (0,0), (-1,-1), 8),
        ("TOPPADDING",     (0,0), (-1,-1), 6),
        ("BOTTOMPADDING",  (0,0), (-1,-1), 6),
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
    method_token = "invoice_age"
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


def _customer_block_flowable(stmt: Dict[str, Any], styles):
    c = stmt.get("contractor") or {}
    name    = _safe(c.get("name") or "")
    country = _safe(c.get("country") or "")
    vat_id  = _safe(c.get("vat_id") or "")
    wfid    = _safe(c.get("wfirma_contractor_id") or "")

    rows = [[Paragraph(
        f"<b>Customer</b><br/>"
        f"<font size='10'>{name}</font><br/>"
        f"<font size='9' color='#475569'>{country}</font>"
        f"<br/><font size='8' color='#475569'>VAT/Tax ID: {vat_id or '—'}</font>"
        f"<br/><font size='7' color='#B0892F'>wFirma id · {wfid or '—'}</font>",
        styles["subtle"],
    )]]
    t = Table(rows, colWidths=[180*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), colors.white),
        ("BOX",           (0,0), (-1,-1), 0.4, _EJ_LINE),
        ("LEFTPADDING",   (0,0), (-1,-1), 10),
        ("RIGHTPADDING",  (0,0), (-1,-1), 10),
        ("TOPPADDING",    (0,0), (-1,-1), 8),
        ("BOTTOMPADDING", (0,0), (-1,-1), 8),
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

    # Aging card.
    method = _aging_method_label(aging.get("method") or "invoice_age")
    aging_rows = [
        ["current", _safe(aging.get("current") or "0.00")],
        ["1–30",    _safe(aging.get("1_30")    or "0.00")],
        ["31–60",   _safe(aging.get("31_60")   or "0.00")],
        ["61–90",   _safe(aging.get("61_90")   or "0.00")],
        ["90+",     _safe(aging.get("90_plus") or "0.00")],
        ["total",   _safe(aging.get("total")   or "0.00")],
    ]
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

def _make_footer_drawer(stmt: Dict[str, Any]):
    """Returns a closure suitable for ``onFirstPage`` / ``onLaterPages``."""
    aging_blocks = stmt.get("aging_per_currency") or {}
    method_token = "invoice_age"
    for v in aging_blocks.values():
        method_token = v.get("method", method_token) or method_token
        break
    method_label = _aging_method_label(method_token)
    generated_at = stmt.get("generated_at") or ""

    def _drawer(canvas, doc):
        canvas.saveState()
        canvas.setFont(_FONT_REG, 7)
        canvas.setFillColor(_EJ_INK_2)
        # Left: seller block (Estrella).
        canvas.drawString(15*mm, 10*mm, "Estrella Jewels Sp. z o.o.")
        # Center: page X of Y. reportlab knows the current page; total
        # is provided via ``doc.page`` only after build, so use a
        # standard "Page X" approximation. For exact "X of Y" we
        # would need a two-pass render — overkill for Phase 10C.
        page_str = f"Page {canvas.getPageNumber()}"
        canvas.drawCentredString(105*mm, 10*mm, page_str)
        # Right: aging-method disclaimer.
        canvas.setFont(_FONT_BOLD, 7)
        canvas.setFillColor(_EJ_GOLD_2)
        right = f"Aging method: {method_label} · Generated {generated_at}"
        canvas.drawRightString(195*mm, 10*mm, right)
        canvas.restoreState()
    return _drawer


# ── Public entry point ────────────────────────────────────────────────────

def render_statement_pdf(statement: Dict[str, Any]) -> bytes:
    """Render a Phase 10B Statement-of-Account dict to PDF bytes.

    Pure function. No I/O, no DB, no wFirma calls. Caller (the route)
    is responsible for producing the dict via the shared
    ``_build_statement_dict`` helper.

    Raises:
      ValueError   — input is not a dict.
      RuntimeError — reportlab build failure (caller catches and
                     converts to 502 STATEMENT_PDF_RENDER_FAILED).
    """
    if not isinstance(statement, dict):
        raise ValueError("statement must be a dict produced by aggregate_statement")

    # Defence-in-depth: drop any forbidden keys before rendering.
    stmt = _strip_forbidden(statement)
    styles = _styles()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=15*mm, rightMargin=15*mm,
        topMargin=18*mm,  bottomMargin=15*mm,
        title="Statement of Account",
        author="Estrella Jewels",
    )

    story: List[Any] = []
    story.append(_masthead_flowable(stmt, styles))
    story.append(Spacer(1, 4))
    story.append(_meta_strip_flowable(stmt, styles))
    story.append(Spacer(1, 6))
    story.append(_customer_block_flowable(stmt, styles))
    story.append(Spacer(1, 8))

    for ccy in (stmt.get("currencies") or []):
        story.extend(_currency_section_flowables(stmt, ccy, styles))

    # Empty notice (when there's no activity at all).
    story.extend(_empty_notice_flowables(stmt, styles))

    # Warnings band rendered last so any single-page print carries
    # them visibly. We do NOT force a page break — letting reportlab
    # decide is friendlier on short statements.
    story.extend(_warnings_flowables(stmt, styles))

    try:
        footer = _make_footer_drawer(stmt)
        doc.build(story, onFirstPage=footer, onLaterPages=footer)
    except Exception as exc:
        raise RuntimeError(f"reportlab build failed: {exc}") from exc

    pdf_bytes = buf.getvalue()
    if not pdf_bytes.startswith(b"%PDF-"):
        raise RuntimeError(
            "reportlab produced output that does not look like a PDF"
        )
    return pdf_bytes


__all__ = ["render_statement_pdf"]
