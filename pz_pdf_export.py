#!/usr/bin/env python3
"""
pz_pdf_export.py — PDF export helper for the PZ pipeline
=========================================================
Renders a process_batch() result dict to a wFirma-style PZ PDF.

Dependency:
    pip install reportlab

Usage:
    from pz_import_processor import process_batch
    from pz_pdf_export import save_pz_pdf

    result = process_batch(inv_paths, zc429_path, rate=3.6506, batch_meta=batch_meta)
    save_pz_pdf(result, "PZ_039_044.pdf", document_no="PZ 12/3/2026")

Design rules:
    - This function does NOT recalculate anything.
    - notes -> format_uwagi(notes) -> PDF  (single path, same as clipboard path)
    - Row fields are read from process_batch() key names; generic aliases accepted too.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


# ── Unicode font registration ─────────────────────────────────────────────────
# Helvetica (ReportLab built-in) does not support Polish characters —
# ł, ś, ć, ż, ń, ó, ą, ę render as black squares (■).
#
# Strategy: probe for DejaVu Sans first (better hinting), fall back to
# Bitstream Vera Sans which ships bundled with ReportLab (zero external dep).
# Either font gives full Latin Extended coverage including all Polish glyphs.

def _register_unicode_fonts() -> tuple[str, str]:
    """Register a Unicode-capable font pair and return (regular, bold) names."""
    import os

    # Candidate paths: user-installed DejaVu → bundled Vera → system DejaVu
    _rl_fonts = os.path.join(os.path.dirname(__file__.replace(
        os.path.basename(__file__), '')), '')   # not used — just a placeholder
    import reportlab as _rl
    _rl_font_dir = os.path.join(os.path.dirname(_rl.__file__), 'fonts')

    candidates = [
        # DejaVu: installed by user (brew, apt, pip-provided path)
        ("/Library/Fonts/DejaVuSans.ttf",         "/Library/Fonts/DejaVuSans-Bold.ttf",         "DejaVu", "DejaVu-Bold"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "DejaVu", "DejaVu-Bold"),
        # Arial Unicode MS: macOS system font — comprehensive Unicode/Polish coverage
        # No separate bold TTF; register same file for both weights (acceptable for PZ docs)
        ("/Library/Fonts/Arial Unicode.ttf", "/Library/Fonts/Arial Unicode.ttf",
         "ArialUnicode", "ArialUnicode"),
        # Bitstream Vera: always present, bundled with reportlab
        # WARNING: incomplete Polish coverage — missing ś U+015B, ż U+017C, ć U+0107, ń U+0144
        # Only reached if neither DejaVu nor Arial Unicode is available
        (os.path.join(_rl_font_dir, "Vera.ttf"),  os.path.join(_rl_font_dir, "VeraBd.ttf"),  "Vera", "Vera-Bold"),
    ]

    for reg_path, bold_path, reg_name, bold_name in candidates:
        if os.path.exists(reg_path) and os.path.exists(bold_path):
            pdfmetrics.registerFont(TTFont(reg_name,  reg_path))
            pdfmetrics.registerFont(TTFont(bold_name, bold_path))
            return reg_name, bold_name

    # Should never reach here — Vera.ttf is always present in reportlab
    raise RuntimeError(
        "No Unicode TTF font found. Install DejaVu: brew install font-dejavu  "
        "or verify your reportlab installation includes Vera.ttf."
    )


_FONT_REG, _FONT_BOLD = _register_unicode_fonts()


# ── Number formatting ─────────────────────────────────────────────────────────

def fmt_pln(value: float) -> str:
    """Polish format: 1 360,18"""
    s = f"{value:,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", " ")


def fmt_qty(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    s = f"{value:.3f}".rstrip("0").rstrip(".")
    return s.replace(".", ",")


# ── UWAGI formatter (PDF variant — no "UWAGI:" prefix; rendered as section header) ─

def format_uwagi(notes: List[str]) -> str:
    """Join note lines; skips blanks.  The 'Uwagi:' header is rendered separately."""
    return "\n".join(n for n in notes if n and str(n).strip())


# ── XML safety ────────────────────────────────────────────────────────────────

def _safe(s: Any) -> str:
    if s is None:
        return ""
    text = str(s)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ── Row field accessor ────────────────────────────────────────────────────────
# process_batch() rows use: pl_desc, total_netto, total_brutto, landed_per_unit
# Generic aliases accepted for compatibility with other callers.

def _row_name(row: Dict) -> str:
    return _safe(
        row.get("pl_desc")           # process_batch() native key
        or row.get("name")
        or row.get("nazwa")
        or ""
    )

def _row_qty(row: Dict) -> float:
    return float(row.get("quantity") or row.get("qty") or 0)

def _row_unit_net(row: Dict) -> float:
    return float(
        row.get("unit_netto_pln")    # process_batch() canonical key
        or row.get("landed_per_unit")  # legacy alias
        or row.get("unit_net_price")
        or row.get("cena_netto")
        or 0
    )

def _row_net(row: Dict) -> float:
    return float(
        row.get("line_netto_pln")    # process_batch() canonical key
        or row.get("total_netto")    # legacy alias
        or row.get("net_value")
        or row.get("total_cost_pln")
        or row.get("wartosc_netto")
        or 0
    )

def _row_gross(row: Dict) -> float:
    return float(
        row.get("line_brutto_pln")   # process_batch() canonical key
        or row.get("total_brutto")   # legacy alias
        or row.get("gross_value")
        or row.get("gross_cost_pln")
        or row.get("wartosc_brutto")
        or 0
    )

def _row_vat(row: Dict) -> str:
    return _safe(row.get("vat_rate") or "23%")


# ── Styles ────────────────────────────────────────────────────────────────────

def _build_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="PZTitle",
        parent=styles["Heading1"],
        fontName=_FONT_BOLD,    # Unicode bold — supports ł ś ć ż ń ó ą ę
        fontSize=13,
        leading=16,
        spaceAfter=8,
        alignment=TA_LEFT,
    ))
    styles.add(ParagraphStyle(
        name="PZBody",
        parent=styles["BodyText"],
        fontName=_FONT_REG,     # Unicode regular
        fontSize=9,
        leading=11,
        spaceAfter=2,
        alignment=TA_LEFT,
    ))
    styles.add(ParagraphStyle(
        name="PZSmall",
        parent=styles["BodyText"],
        fontName=_FONT_REG,     # Unicode regular
        fontSize=8,
        leading=10,
        spaceAfter=1,
        alignment=TA_LEFT,
    ))
    return styles


# ── Items table ───────────────────────────────────────────────────────────────

def _build_items_table(rows: List[Dict[str, Any]], styles) -> Table:
    data = [[
        Paragraph("<b>Lp</b>",              styles["PZSmall"]),
        Paragraph("<b>Nazwa</b>",           styles["PZSmall"]),
        Paragraph("<b>Jedn</b>",            styles["PZSmall"]),
        Paragraph("<b>Ilość</b>",           styles["PZSmall"]),
        Paragraph("<b>Cena netto</b>",      styles["PZSmall"]),
        Paragraph("<b>Stawka</b>",          styles["PZSmall"]),
        Paragraph("<b>Wartość netto</b>",   styles["PZSmall"]),
        Paragraph("<b>Wartość brutto</b>",  styles["PZSmall"]),
    ]]

    for i, row in enumerate(rows, 1):
        data.append([
            Paragraph(str(i),                    styles["PZSmall"]),
            Paragraph(_row_name(row),            styles["PZSmall"]),
            Paragraph("szt.",                    styles["PZSmall"]),
            Paragraph(fmt_qty(_row_qty(row)),    styles["PZSmall"]),
            Paragraph(fmt_pln(_row_unit_net(row)), styles["PZSmall"]),
            Paragraph(_row_vat(row),             styles["PZSmall"]),
            Paragraph(fmt_pln(_row_net(row)),    styles["PZSmall"]),
            Paragraph(fmt_pln(_row_gross(row)),  styles["PZSmall"]),
        ])

    table = Table(
        data,
        colWidths=[10*mm, 78*mm, 12*mm, 14*mm, 22*mm, 14*mm, 22*mm, 24*mm],
        repeatRows=1,
    )
    table.setStyle(TableStyle([
        ("BACKGROUND",   (0, 0), (-1, 0), colors.HexColor("#EDEDED")),
        ("FONTNAME",     (0, 0), (-1, 0), _FONT_BOLD),
        ("ALIGN",        (0, 0), (0, -1), "CENTER"),
        ("ALIGN",        (2, 1), (-1, -1), "CENTER"),
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
        ("GRID",         (0, 0), (-1, -1), 0.35, colors.grey),
        ("LEFTPADDING",  (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING",   (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
    ]))
    return table


# ── Public API ────────────────────────────────────────────────────────────────

def save_pz_pdf(
    result: Dict[str, Any],
    output_path: str | Path,
    document_no: str = "",
    warehouse: str = "Główny",
    recipient: Dict[str, str] | None = None,
    supplier: Dict[str, str] | None = None,
) -> Path:
    """
    Render a process_batch() result to a PDF and write it to output_path.

    Parameters
    ----------
    result       : dict returned by process_batch()
    output_path  : destination .pdf path
    document_no  : PZ document number shown in the header (e.g. "PZ 12/3/2026")
    warehouse    : warehouse name shown in the header (default "Główny")
    recipient    : overrides default Estrella Jewels recipient block
    supplier     : overrides default Estrella Jewels LLP supplier block

    Returns the resolved output Path.
    """
    styles     = _build_styles()
    output_path = Path(output_path)

    rows  = result.get("rows",  [])
    notes = result.get("notes", [])
    zc    = result.get("zc429", {})

    if recipient is None:
        recipient = {
            "name":    "ESTRELLA JEWELS Sp. z o. o. SPÓŁKA KOMANDYTOWA",
            "address": "ul. Wybrzeże Kościuszkowskie 31/33, 00-379 Warszawa",
            "nip":     "5252812119",
        }

    if supplier is None:
        supplier = {
            "name":    "ESTRELLA JEWELS LLP.",
            "address": "312, OPTIONS PRIMO PREMISES CHSL, MAROL INDUSTRIAL ESTATE, "
                       "MIDC, 400093 ANDHERI EAST, MUMBAI",
            "country": "Indie",
        }

    # Clearance date → DD.MM.YYYY
    issue_date = (zc.get("clearance_date") or zc.get("release_date")
                  or zc.get("acceptance_date") or "")
    if isinstance(issue_date, str) and "-" in issue_date and len(issue_date) >= 10:
        yyyy, mo, dd = issue_date[:10].split("-")
        issue_date = f"{dd}.{mo}.{yyyy}"

    doc_no = document_no or result.get("document_no") or "PZ"

    # Totals: prefer pre-computed keys from process_batch(); fall back to summing rows
    total_net   = float(result.get("total_net")   or sum(_row_net(r)   for r in rows))
    total_gross = float(result.get("total_gross") or sum(_row_gross(r) for r in rows))

    # ── Build story ───────────────────────────────────────────────────────────
    story = []

    story.append(Paragraph(_safe(doc_no), styles["PZTitle"]))
    story.append(Paragraph(f"Data wystawienia: {_safe(issue_date)}", styles["PZBody"]))
    story.append(Paragraph(f"Magazyn: {_safe(warehouse)}", styles["PZBody"]))
    story.append(Spacer(1, 4))

    header_table = Table([[
        Paragraph(
            f"<b>Odbiorca</b><br/>"
            f"{_safe(recipient.get('name',''))}<br/>"
            f"{_safe(recipient.get('address',''))}<br/>"
            f"NIP: {_safe(recipient.get('nip',''))}",
            styles["PZBody"],
        ),
        Paragraph(
            f"<b>Dostawca</b><br/>"
            f"{_safe(supplier.get('name',''))}<br/>"
            f"{_safe(supplier.get('address',''))}<br/>"
            f"{_safe(supplier.get('country',''))}",
            styles["PZBody"],
        ),
    ]], colWidths=[90*mm, 90*mm])
    header_table.setStyle(TableStyle([
        ("BOX",          (0, 0), (-1, -1), 0.5,  colors.grey),
        ("INNERGRID",    (0, 0), (-1, -1), 0.35, colors.grey),
        ("VALIGN",       (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING",   (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
    ]))

    story.append(header_table)
    story.append(Spacer(1, 6))
    story.append(_build_items_table(rows, styles))
    story.append(Spacer(1, 6))

    # UWAGI — single path: notes → format_uwagi(notes) → PDF
    # The audit note is appended here; it describes the allocation method used.
    audit_note = "Koszty frachtu i cła rozliczono proporcjonalnie do wartości pozycji."
    all_notes  = list(notes) + [audit_note]
    story.append(Paragraph("<b>Uwagi:</b>", styles["PZBody"]))
    for line in format_uwagi(all_notes).splitlines():
        story.append(Paragraph(_safe(line), styles["PZSmall"]))

    story.append(Spacer(1, 8))

    totals_table = Table([
        ["Razem netto",   f"{fmt_pln(total_net)} PLN"],
        ["Razem brutto",  f"{fmt_pln(total_gross)} PLN"],
    ], colWidths=[140*mm, 40*mm])
    totals_table.setStyle(TableStyle([
        ("BOX",          (0, 0), (-1, -1), 0.5,  colors.grey),
        ("INNERGRID",    (0, 0), (-1, -1), 0.35, colors.grey),
        ("FONTNAME",     (0, 0), (-1, -1), _FONT_BOLD),
        ("ALIGN",        (1, 0), (1, -1), "RIGHT"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING",   (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
    ]))
    story.append(totals_table)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=12*mm,
        rightMargin=12*mm,
        topMargin=12*mm,
        bottomMargin=12*mm,
        title=doc_no,
    )
    doc.build(story)
    return output_path
