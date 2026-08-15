"""Insurance Export Statement PDF — declaration print renderer.

Pure function: receives already-resolved selection data from
``insurance_export_statement.resolve_declaration_selection`` and renders the
declaration PDF. NO monetary math happens here beyond printing the strings the
authority produced — totals arrive pre-computed and quantized.

Layout: ReportLab landscape(A4), 8 mm margins (commercial_packing_list
pattern); page-number footer via ``canvas.getPageNumber()``
(statement_pdf_renderer pattern). Fonts registered under new idempotent
aliases ``EJInsExp`` / ``EJInsExp-Bold`` so co-import with other renderers
never collides.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_EJ_BRAND = colors.HexColor("#0B3D2E")
_EJ_GOLD = colors.HexColor("#C9A24B")
_EJ_CREAM = colors.HexColor("#FBF8F1")
_EJ_INK = colors.HexColor("#0F172A")
_EJ_RED = colors.HexColor("#B91C1C")
_EJ_MUTED = colors.HexColor("#64748B")
_EJ_LINE = colors.HexColor("#D6D3CB")

_PAGE_W, _PAGE_H = landscape(A4)
_MARGIN = 8 * mm


def _register_unicode_fonts() -> Tuple[str, str]:
    """Register a Unicode-capable font pair under EJInsExp aliases.

    Mirrors statement_pdf_renderer so Polish contractor names render without
    missing-glyph squares; distinct alias keeps registration idempotent.
    """
    import reportlab as _rl

    _rl_font_dir = os.path.join(os.path.dirname(_rl.__file__), "fonts")
    registered = pdfmetrics.getRegisteredFontNames()
    if "EJInsExp" in registered and "EJInsExp-Bold" in registered:
        return "EJInsExp", "EJInsExp-Bold"
    candidates = [
        ("C:\\Windows\\Fonts\\DejaVuSans.ttf", "C:\\Windows\\Fonts\\DejaVuSans-Bold.ttf"),
        ("/Library/Fonts/DejaVuSans.ttf", "/Library/Fonts/DejaVuSans-Bold.ttf"),
        (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ),
        ("C:\\Windows\\Fonts\\arial.ttf", "C:\\Windows\\Fonts\\arialbd.ttf"),
        (
            os.path.join(_rl_font_dir, "Vera.ttf"),
            os.path.join(_rl_font_dir, "VeraBd.ttf"),
        ),
    ]
    for reg, bold in candidates:
        if os.path.exists(reg) and os.path.exists(bold):
            try:
                pdfmetrics.registerFont(TTFont("EJInsExp", reg))
                pdfmetrics.registerFont(TTFont("EJInsExp-Bold", bold))
                return "EJInsExp", "EJInsExp-Bold"
            except Exception:
                continue
    raise RuntimeError(
        "No Unicode TTF font found for insurance export PDF (install DejaVu)."
    )


_FONT_REG, _FONT_BOLD = _register_unicode_fonts()

_CELL = ParagraphStyle(
    "ins_cell", fontName=_FONT_REG, fontSize=7.2, leading=9, textColor=_EJ_INK
)
_CELL_R = ParagraphStyle("ins_cell_r", parent=_CELL, alignment=TA_RIGHT)
_CELL_B = ParagraphStyle("ins_cell_b", parent=_CELL, fontName=_FONT_BOLD)
_CELL_BR = ParagraphStyle("ins_cell_br", parent=_CELL_B, alignment=TA_RIGHT)
_CELL_RED_R = ParagraphStyle("ins_cell_red", parent=_CELL_R, textColor=_EJ_RED)
_CELL_ADJ = ParagraphStyle(
    "ins_cell_adj", parent=_CELL, leftIndent=6, textColor=_EJ_MUTED
)
_HDR = ParagraphStyle(
    "ins_hdr",
    fontName=_FONT_BOLD,
    fontSize=7.4,
    leading=9,
    textColor=colors.white,
    alignment=TA_CENTER,
)


def _fmt(value: Optional[str], dash: str = "\u2014") -> str:
    return value if value not in (None, "") else dash


def _num_cell(value: Optional[str], bold: bool = False) -> Paragraph:
    text = _fmt(value)
    if text.startswith("-"):
        return Paragraph(text, _CELL_RED_R)
    return Paragraph(text, _CELL_BR if bold else _CELL_R)


def _page_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont(_FONT_REG, 7)
    canvas.setFillColor(_EJ_MUTED)
    canvas.drawString(_MARGIN, 5 * mm, "Estrella Jewels — Insurance Export Statement")
    canvas.drawRightString(
        _PAGE_W - _MARGIN, 5 * mm, "Page %d" % canvas.getPageNumber()
    )
    canvas.restoreState()


_HEADERS_PL = [
    "Kontrahent",
    "Nr dokumentu",
    "Data wystawienia",
    "Waluta",
    "Inv CIF",
    "10% addition",
    "Sum Insured",
    "Exch Rate",
    "Sum Insured INR",
    "Insurance Recovered",
]


def _col_widths(show_recovered: bool) -> List[float]:
    if show_recovered:
        widths_mm = [48, 38, 22, 14, 28, 24, 28, 22, 32, 25]
    else:
        widths_mm = [58, 42, 24, 14, 30, 26, 30, 23, 34]
    return [w * mm for w in widths_mm]


def _recovered_text(row: Dict[str, Any]) -> str:
    rec = row.get("insurance_recovered") or {}
    amount = rec.get("amount")
    if not amount or amount == "0.00":
        return "\u2014"
    return "%s %s" % (amount, rec.get("currency") or "")


def render_insurance_export_statement_pdf(
    report: Optional[Dict[str, Any]],
    *,
    selected_rows: List[Dict[str, Any]],
    selected_adjustments: List[Dict[str, Any]],
    declaration_totals: Dict[str, Any],
    period: Dict[str, Any],
    columns: Optional[Dict[str, Any]] = None,
    include_adjustments: bool = True,
    seller: Optional[Dict[str, Any]] = None,
) -> bytes:
    columns = columns or {}
    show_recovered = bool(columns.get("insurance_recovered", True))
    n_cols = 10 if show_recovered else 9
    headers = _HEADERS_PL if show_recovered else _HEADERS_PL[:9]

    if not include_adjustments:
        selected_adjustments = []

    # Group selected rows by contractor, preserving selection (report) order.
    groups: List[Dict[str, Any]] = []
    group_index: Dict[str, Dict[str, Any]] = {}
    for row in selected_rows:
        key = row.get("contractor_id") or "name:%s" % row.get("contractor_name")
        grp = group_index.get(key)
        if grp is None:
            grp = {"name": row.get("contractor_name") or "\u2014", "rows": [], "adjustments": []}
            group_index[key] = grp
            groups.append(grp)
        grp["rows"].append(row)
    selected_doc_ids = {r["invoice_id"] for r in selected_rows}
    for adj in selected_adjustments:
        parent = adj.get("parent_invoice_id")
        key = adj.get("contractor_id") or "name:%s" % adj.get("contractor_name")
        if parent and parent in selected_doc_ids:
            # nest under the parent's contractor group
            for grp in groups:
                if any(r["invoice_id"] == parent for r in grp["rows"]):
                    grp["adjustments"].append(adj)
                    break
            else:
                grp = group_index.setdefault(
                    key,
                    {"name": adj.get("contractor_name") or "\u2014", "rows": [], "adjustments": []},
                )
                if grp not in groups:
                    groups.append(grp)
                grp["adjustments"].append(adj)
        else:
            grp = group_index.get(key)
            if grp is None:
                grp = {"name": adj.get("contractor_name") or "\u2014", "rows": [], "adjustments": []}
                group_index[key] = grp
                groups.append(grp)
            grp["adjustments"].append(adj)

    data: List[List[Any]] = [[Paragraph(h, _HDR) for h in headers]]
    styles: List[Tuple] = []

    def _doc_row(row: Dict[str, Any], first_in_group: bool) -> List[Any]:
        cells = [
            Paragraph(row.get("contractor_name") or "", _CELL_B)
            if first_in_group
            else Paragraph("", _CELL),
            Paragraph(_fmt(row.get("fullnumber")), _CELL),
            Paragraph(_fmt(row.get("date")), _CELL),
            Paragraph(_fmt(row.get("currency")), _CELL),
            _num_cell(row.get("inv_cif")),
            _num_cell(row.get("plus_10_pct")),
            _num_cell(row.get("sum_insured")),
            _num_cell(row.get("fx_rate")),
            _num_cell(row.get("sum_insured_inr")),
        ]
        if show_recovered:
            cells.append(Paragraph(_recovered_text(row), _CELL_R))
        return cells

    def _adj_row(adj: Dict[str, Any]) -> List[Any]:
        cells = [
            Paragraph("", _CELL),
            Paragraph("\u2014 %s" % _fmt(adj.get("fullnumber")), _CELL_ADJ),
            Paragraph(_fmt(adj.get("date")), _CELL_ADJ),
            Paragraph(_fmt(adj.get("currency")), _CELL_ADJ),
            _num_cell(adj.get("inv_cif")),
            _num_cell(adj.get("plus_10_pct")),
            _num_cell(adj.get("sum_insured")),
            _num_cell(adj.get("fx_rate")),
            _num_cell(adj.get("sum_insured_inr")),
        ]
        if show_recovered:
            cells.append(Paragraph(_recovered_text(adj), _CELL_R))
        return cells

    from decimal import Decimal

    for grp in groups:
        group_start = len(data)
        for i, row in enumerate(grp["rows"]):
            data.append(_doc_row(row, i == 0))
        for adj in grp["adjustments"]:
            data.append(_adj_row(adj))
        # group subtotal — printed sum of the group's already-quantized INR
        # strings (presentation aggregation of authority values, not new math)
        total = Decimal("0")
        for r in grp["rows"] + grp["adjustments"]:
            v = r.get("sum_insured_inr")
            if v:
                total += Decimal(v)
        sub = [Paragraph("", _CELL)] * n_cols
        sub[1] = Paragraph("Razem: %s" % grp["name"], _CELL_B)
        sub[8] = _num_cell(str(total.quantize(Decimal("0.01"))), bold=True)
        data.append(sub)
        styles.append(
            ("BACKGROUND", (0, len(data) - 1), (-1, len(data) - 1), _EJ_CREAM)
        )
        styles.append(
            ("LINEABOVE", (0, group_start), (-1, group_start), 0.5, _EJ_LINE)
        )

    def _totals_row(label: str, value: Optional[str]) -> None:
        row = [Paragraph("", _CELL)] * n_cols
        row[1] = Paragraph(
            label,
            ParagraphStyle(
                "ins_total_lbl",
                parent=_CELL_B,
                textColor=colors.white,
            ),
        )
        row[8] = Paragraph(
            _fmt(value),
            ParagraphStyle(
                "ins_total_val",
                parent=_CELL_BR,
                textColor=colors.white,
            ),
        )
        data.append(row)
        styles.append(
            ("BACKGROUND", (0, len(data) - 1), (-1, len(data) - 1), _EJ_BRAND)
        )

    _totals_row("TOTAL", declaration_totals.get("sum_insured_inr_documents"))
    if selected_adjustments:
        _totals_row(
            "GRAND TOTAL", declaration_totals.get("sum_insured_inr_grand")
        )

    table = Table(data, colWidths=_col_widths(show_recovered), repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _EJ_BRAND),
                ("LINEBELOW", (0, 0), (-1, 0), 1, _EJ_GOLD),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("GRID", (0, 0), (-1, -1), 0.25, _EJ_LINE),
            ]
            + styles
        )
    )

    seller = seller or {}
    seller_name = seller.get("name") or "ESTRELLA JEWELS LLP SP. Z O.O., SP. K."
    masthead = [
        Paragraph(
            seller_name,
            ParagraphStyle(
                "ins_mast1",
                fontName=_FONT_BOLD,
                fontSize=13,
                leading=16,
                textColor=_EJ_BRAND,
                alignment=TA_CENTER,
            ),
        ),
        Paragraph(
            "STATEMENT OF EXPORT SHIPMENT",
            ParagraphStyle(
                "ins_mast2",
                fontName=_FONT_BOLD,
                fontSize=10,
                leading=13,
                textColor=_EJ_GOLD,
                alignment=TA_CENTER,
            ),
        ),
        Paragraph(
            "Period: %s \u2013 %s"
            % (period.get("from") or "", period.get("to") or ""),
            ParagraphStyle(
                "ins_mast3",
                fontName=_FONT_REG,
                fontSize=8.5,
                leading=11,
                textColor=_EJ_INK,
                alignment=TA_CENTER,
            ),
        ),
    ]

    story: List[Any] = list(masthead)
    story.append(Spacer(1, 4 * mm))
    story.append(table)

    recovered = (declaration_totals or {}).get("insurance_recovered") or {}
    if show_recovered and recovered:
        story.append(Spacer(1, 3 * mm))
        parts = ", ".join(
            "%s %s" % (amt, ccy) for ccy, amt in sorted(recovered.items())
        )
        story.append(
            Paragraph(
                "Insurance recovered from customers (per currency): %s" % parts,
                ParagraphStyle(
                    "ins_recovered_note",
                    parent=_CELL,
                    fontSize=7.5,
                    textColor=_EJ_MUTED,
                ),
            )
        )

    story.append(Spacer(1, 12 * mm))
    sig_style = ParagraphStyle(
        "ins_sig", fontName=_FONT_REG, fontSize=8, leading=10, alignment=TA_CENTER
    )
    sig = Table(
        [
            [
                Paragraph("_______________________", sig_style),
                Paragraph("_______________________", sig_style),
                Paragraph("_______________________", sig_style),
            ],
            [
                Paragraph("Prepared by", sig_style),
                Paragraph("Authorised Signatory", sig_style),
                Paragraph("Date + Company Stamp", sig_style),
            ],
        ],
        colWidths=[(_PAGE_W - 2 * _MARGIN) / 3.0] * 3,
    )
    story.append(sig)

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=_MARGIN,
        rightMargin=_MARGIN,
        topMargin=_MARGIN,
        bottomMargin=10 * mm,
        title="Insurance Export Statement %s - %s"
        % (period.get("from") or "", period.get("to") or ""),
    )
    doc.build(story, onFirstPage=_page_footer, onLaterPages=_page_footer)
    return buf.getvalue()


__all__ = ["render_insurance_export_statement_pdf"]
