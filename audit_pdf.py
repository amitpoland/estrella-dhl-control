#!/usr/bin/env python3
"""
audit_pdf.py — Signed-style audit memo PDF generator
=====================================================
Generates a structured, professional audit memo as a PDF using reportlab.platypus.

Sections:
  Header   — batch metadata, MRN, clearance date
  1. Parties           — exporter, importer, NIP
  2. Document chain    — invoices, AWB, MRN, status
  3. Address analysis  — registered office, warehouse, conclusion
  4. Value reconciliation — per-invoice FOB+F+I, totals, duty
  5. Freight logic     — allocation methodology statement
  6. Risk assessment   — score, level, failed checks
  7. Final statement   — EN/PL bilingual conclusion
  8. Signature block   — prepared by + approval line

Usage:
    from audit_pdf import generate_audit_pdf
    path = generate_audit_pdf(output_path, audit_data)

audit_data dict (produced by audit_agent.build_audit_report):
    batch_id, doc_no, mrn, clearance_date,
    score, risk_level, failed_checks,
    c1..c6 (check result dicts),
    overall_en, overall_pl,
    invoices (raw list), zc429 (raw dict), nbp (raw dict)
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

# ── Unicode font registration ─────────────────────────────────────────────────
# Priority-ordered list of fonts with full Unicode/Polish glyph coverage.

_FONT_CANDIDATES = [
    "/Library/Fonts/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode MS.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]

_font_regular: str = "Helvetica"
_font_bold:    str = "Helvetica-Bold"
_fonts_registered: bool = False


def _register_audit_fonts() -> tuple[str, str]:
    """
    Register the first available Unicode-capable TTF font for use in audit PDFs.
    Returns (font_regular_name, font_bold_name).
    Falls back to Helvetica if no TTF is found (non-Latin glyphs will be lost).
    """
    global _font_regular, _font_bold, _fonts_registered
    if _fonts_registered:
        return _font_regular, _font_bold

    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont("AuditUnicode",     path))
                pdfmetrics.registerFont(TTFont("AuditUnicodeBold", path))
                _font_regular      = "AuditUnicode"
                _font_bold         = "AuditUnicodeBold"
                _fonts_registered  = True
                return _font_regular, _font_bold
            except Exception:
                continue  # broken TTF — try next

    _fonts_registered = True   # avoid re-attempting on every call
    return _font_regular, _font_bold


# ── Colour palette ────────────────────────────────────────────────────────────
_DARK   = colors.HexColor("#1a1a2e")
_ACCENT = colors.HexColor("#16213e")
_GREEN  = colors.HexColor("#0f7a55")
_RED    = colors.HexColor("#c0392b")
_AMBER  = colors.HexColor("#d68910")
_LIGHT  = colors.HexColor("#f5f5f5")
_BORDER = colors.HexColor("#cccccc")

_RISK_COLOURS = {
    "LOW RISK":    _GREEN,
    "MEDIUM RISK": _AMBER,
    "HIGH RISK":   _RED,
}


# ── Style factory ─────────────────────────────────────────────────────────────

def _make_styles() -> dict:
    fr, fb = _register_audit_fonts()
    S = {}

    S["title"] = ParagraphStyle(
        "title",
        fontName=fb,
        fontSize=14,
        textColor=_DARK,
        alignment=TA_CENTER,
        spaceAfter=2,
    )
    S["subtitle"] = ParagraphStyle(
        "subtitle",
        fontName=fr,
        fontSize=9,
        textColor=colors.HexColor("#555555"),
        alignment=TA_CENTER,
        spaceAfter=8,
    )
    S["section"] = ParagraphStyle(
        "section",
        fontName=fb,
        fontSize=10,
        textColor=_ACCENT,
        spaceBefore=10,
        spaceAfter=4,
        borderPadding=(2, 0, 2, 0),
    )
    S["body"] = ParagraphStyle(
        "body",
        fontName=fr,
        fontSize=8.5,
        leading=13,
        textColor=_DARK,
    )
    S["body_bold"] = ParagraphStyle(
        "body_bold",
        fontName=fb,
        fontSize=8.5,
        leading=13,
        textColor=_DARK,
    )
    S["mono"] = ParagraphStyle(
        "mono",
        fontName=fr,
        fontSize=8,
        leading=12,
        textColor=_DARK,
    )
    S["footer"] = ParagraphStyle(
        "footer",
        fontName=fr,
        fontSize=7.5,
        textColor=colors.HexColor("#888888"),
        alignment=TA_CENTER,
    )
    S["score_pass"] = ParagraphStyle(
        "score_pass",
        fontName=fb,
        fontSize=13,
        textColor=_GREEN,
        alignment=TA_CENTER,
    )
    S["score_medium"] = ParagraphStyle(
        "score_pass",
        fontName=fb,
        fontSize=13,
        textColor=_AMBER,
        alignment=TA_CENTER,
    )
    S["score_fail"] = ParagraphStyle(
        "score_pass",
        fontName=fb,
        fontSize=13,
        textColor=_RED,
        alignment=TA_CENTER,
    )
    S["sign_line"] = ParagraphStyle(
        "sign_line",
        fontName=fr,
        fontSize=8.5,
        textColor=_DARK,
        spaceBefore=6,
    )
    return S


# ── Small helpers ─────────────────────────────────────────────────────────────

def _hr(elems: list, colour=_BORDER, thickness: float = 0.5) -> None:
    elems.append(HRFlowable(width="100%", thickness=thickness, color=colour, spaceAfter=4, spaceBefore=4))


def _kv_table(rows: List[tuple], S: dict, col_widths=None) -> Table:
    """Two-column key→value table with zebra shading."""
    fr, fb = _register_audit_fonts()
    col_widths = col_widths or [55 * mm, 105 * mm]
    data = [[Paragraph(f"<b>{k}</b>", S["body"]), Paragraph(str(v), S["body"])] for k, v in rows]
    t = Table(data, colWidths=col_widths, hAlign="LEFT")
    style = [
        ("FONTNAME",    (0, 0), (-1, -1), fr),
        ("FONTSIZE",    (0, 0), (-1, -1), 8.5),
        ("LEADING",     (0, 0), (-1, -1), 13),
        ("VALIGN",      (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",  (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING",(0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, _LIGHT]),
        ("BOX",     (0, 0), (-1, -1), 0.3, _BORDER),
        ("INNERGRID",(0, 0), (-1, -1), 0.3, _BORDER),
    ]
    t.setStyle(TableStyle(style))
    return t


def _verdict_str(val: Optional[bool]) -> str:
    if val is True:  return "✓ MATCH"
    if val is False: return "✗ MISMATCH"
    return "~ NOT VERIFIED"


def _fmt_usd(v: float) -> str:
    return f"${v:,.2f}"

def _fmt_pln(v: float) -> str:
    return f"{v:,.2f} PLN"


# ── Score badge ───────────────────────────────────────────────────────────────

def _score_badge(score: int, risk_level: str, S: dict) -> Table:
    colour = _RISK_COLOURS.get(risk_level, _AMBER)
    cell_text = f"<font color='#{colour.hexval()[2:]}'><b>{score}/100</b></font>"
    level_text = f"<font color='#{colour.hexval()[2:]}'><b>{risk_level}</b></font>"
    data = [[Paragraph(cell_text, S["score_pass"]), Paragraph(level_text, S["score_pass"])]]
    t = Table(data, colWidths=[80 * mm, 80 * mm], hAlign="CENTER")
    t.setStyle(TableStyle([
        ("BOX",   (0, 0), (-1, -1), 1.0, colour),
        ("TOPPADDING",   (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    return t


# ── Per-invoice value table ───────────────────────────────────────────────────

def _per_invoice_table(per_inv_checks: List[dict], S: dict) -> Table:
    fr, fb = _register_audit_fonts()
    header = ["Invoice", "FOB", "Freight", "Insurance", "= CIF", "Stated", "OK?"]
    rows = [header]
    for ch in per_inv_checks:
        rows.append([
            ch["invoice_no"],
            _fmt_usd(ch["fob"]),
            _fmt_usd(ch["freight"]),
            _fmt_usd(ch["insurance"]),
            _fmt_usd(ch["computed"]),
            _fmt_usd(ch["stated"]),
            "✓" if ch["ok"] else "✗",
        ])
    col_w = [48*mm, 18*mm, 18*mm, 18*mm, 18*mm, 18*mm, 10*mm]
    t = Table(rows, colWidths=col_w, hAlign="LEFT")
    style = [
        ("FONTNAME",     (0, 0), (-1, -1), fr),
        ("FONTSIZE",     (0, 0), (-1, -1), 7.5),
        ("LEADING",      (0, 0), (-1, -1), 11),
        ("FONTNAME",     (0, 0), (-1, 0), fb),
        ("BACKGROUND",   (0, 0), (-1, 0), _ACCENT),
        ("TEXTCOLOR",    (0, 0), (-1, 0), colors.white),
        ("ALIGN",        (1, 0), (-1, -1), "RIGHT"),
        ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",   (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
        ("LEFTPADDING",  (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, _LIGHT]),
        ("BOX",          (0, 0), (-1, -1), 0.3, _BORDER),
        ("INNERGRID",    (0, 0), (-1, -1), 0.3, _BORDER),
    ]
    # Colour the OK? column
    for i, ch in enumerate(per_inv_checks, 1):
        c = _GREEN if ch["ok"] else _RED
        style.append(("TEXTCOLOR", (6, i), (6, i), c))
        style.append(("FONTNAME",  (6, i), (6, i), fb))
    t.setStyle(TableStyle(style))
    return t


# ── Main generator ────────────────────────────────────────────────────────────

def generate_audit_pdf(output_path: Path, audit_data: Dict[str, Any]) -> Path:
    """
    Generate the signed-style audit memo PDF.

    audit_data keys:
        batch_id, doc_no, mrn, clearance_date
        score, risk_level, failed_checks
        c1, c2, c3, c4, c5, c6     (check result dicts from audit_agent)
        overall_en, overall_pl      (final assessment strings)
        invoices, zc429, nbp        (raw result sub-dicts)
        line_count, total_net, total_gross, duty_pln
    """
    output_path = Path(output_path)
    fr, fb = _register_audit_fonts()
    S = _make_styles()

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=20 * mm,
    )

    c1 = audit_data.get("c1", {})
    c2 = audit_data.get("c2", {})
    c3 = audit_data.get("c3", {})
    c4 = audit_data.get("c4", {})
    c5 = audit_data.get("c5", {})
    c6 = audit_data.get("c6", {})
    zc429        = audit_data.get("zc429", {})
    nbp          = audit_data.get("nbp", {})
    invoices     = audit_data.get("invoices", [])
    inv_totals   = audit_data.get("invoice_totals", {})
    settle_mode  = audit_data.get("settlement_mode", "standard")

    score       = audit_data.get("score", 0)
    risk_level  = audit_data.get("risk_level", "UNKNOWN")
    failed      = audit_data.get("failed_checks", [])
    batch_id    = audit_data.get("batch_id", "")
    doc_no      = audit_data.get("doc_no", "")
    mrn         = audit_data.get("mrn") or zc429.get("mrn", "(not parsed)")
    clr_date    = audit_data.get("clearance_date") or zc429.get("clearance_date", "(not parsed)")
    overall_en  = audit_data.get("overall_en", "")
    overall_pl  = audit_data.get("overall_pl", "")
    generated   = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())

    elems = []
    A = elems.append

    # ── Header ────────────────────────────────────────────────────────────────
    A(Paragraph("ESTRELLA JEWELS Sp. z o.o. Sp.k.", S["title"]))
    A(Paragraph("INTERNAL IMPORT COMPLIANCE AUDIT MEMO", S["title"]))
    _hr(elems, _ACCENT, 1.2)
    A(Spacer(1, 2))

    vat_mode_str = (
        "Art. 33a — deferred VAT (reverse charge)"
        if settle_mode == "art33a"
        else "Standard — VAT paid at customs"
    )
    agent_str = zc429.get("agent", "") or "(not parsed)"
    meta = [
        ("Batch ID",        batch_id),
        ("Document",        doc_no or "(not specified)"),
        ("MRN",             mrn),
        ("Clearance date",  clr_date),
        ("VAT mode",        vat_mode_str),
        ("Customs agent",   agent_str),
        ("Generated",       generated),
        ("Engine version",  "audit_agent v2 / audit_pdf v1"),
    ]
    A(_kv_table(meta, S))
    A(Spacer(1, 8))

    # ── Risk score badge ──────────────────────────────────────────────────────
    A(_score_badge(score, risk_level, S))
    A(Spacer(1, 10))

    # ── Section 1: Parties ────────────────────────────────────────────────────
    A(Paragraph("1. PARTIES", S["section"]))
    _hr(elems)
    parties = [
        ("Exporter",          c1.get("invoice_value") or "(not parsed)"),
        ("Exporter (SAD)",    c1.get("sad_value")     or "(not parsed)"),
        ("Exporter match",    _verdict_str(c1.get("result"))),
        ("Importer",          c2.get("invoice_name")  or "(not parsed)"),
        ("Importer (SAD)",    c2.get("sad_name")      or "(not parsed)"),
        ("Importer match",    _verdict_str(c2.get("name_result"))),
        ("NIP / VAT ID",      c2.get("master_nip",    "5252812119")),
        ("NIP match",         _verdict_str(c2.get("nip_result"))),
        ("Customs agent",     zc429.get("agent")      or "(not parsed)"),
    ]
    A(_kv_table(parties, S))
    A(Spacer(1, 8))

    # ── Section 2: Document chain ─────────────────────────────────────────────
    A(Paragraph("2. DOCUMENT CHAIN", S["section"]))
    _hr(elems)
    sad_refs  = c4.get("sad_refs", [])
    pdf_refs  = c4.get("pdf_refs", [])
    awb_list  = c6.get("awb_digits", []) or c6.get("refs", [])
    chain = [
        ("Invoices (SAD N935)", ", ".join(sad_refs) or "(not parsed)"),
        ("Invoices (PDF set)",  ", ".join(pdf_refs) or "(not parsed)"),
        ("Invoice chain",       _verdict_str(c4.get("result")) + f"  — {c4.get('severity_en', '')}"),
        ("AWB / N740",          ", ".join(awb_list) or "(not extracted from SAD)"),
        ("Transport match",     _verdict_str(c6.get("result"))),
        ("MRN",                 mrn),
        ("LRN",                 zc429.get("lrn") or "(not parsed)"),
    ]
    A(_kv_table(chain, S))
    A(Spacer(1, 8))

    # ── Section 3: Address analysis ───────────────────────────────────────────
    A(Paragraph("3. ADDRESS ANALYSIS", S["section"]))
    _hr(elems)
    addr = [
        ("Registered office",    c3.get("master_reg_addr", "")),
        ("Invoice delivery addr",c3.get("invoice_addr", "(not parsed)")),
        ("Invoice address type", c3.get("invoice_type_en", "(unknown)")),
        ("SAD delivery addr",    c3.get("sad_addr", "(not parsed)")),
        ("Classification",       _verdict_str(c3.get("consistent"))),
        ("Conclusion",           (
            "Warehouse delivery to registered importer — consistent."
            if c3.get("consistent") is True else
            "Address inconsistency detected — requires explanation."
            if c3.get("consistent") is False else
            "Could not classify address from available data."
        )),
    ]
    A(_kv_table(addr, S))
    A(Spacer(1, 8))

    # ── Section 4: Value reconciliation ──────────────────────────────────────
    A(Paragraph("4. VALUE RECONCILIATION", S["section"]))
    _hr(elems)

    A(Paragraph("4a. Per-invoice arithmetic: FOB + Freight + Insurance = CIF", S["body_bold"]))
    A(Spacer(1, 3))
    if c5.get("per_inv_checks"):
        A(_per_invoice_table(c5["per_inv_checks"], S))
    A(Spacer(1, 6))

    # AWB customs value = invoice CIF total (what was declared to customs)
    # SAD invoice value = SAD CIF parsed from field 14.06
    # Both are already computed in c5 from _check5_values()
    awb_val     = c5.get("inv_cif")   # invoice CIF = AWB declared value
    sad_inv_val = c5.get("sad_cif")   # SAD invoice/CIF value (field 14.06)
    stat_val    = zc429.get("statistical_value_pln")   # from our parser (field 99.06)
    goods_desc  = zc429.get("goods_description", "")   # from our parser (field 31)
    cn_code     = zc429.get("cn_code", "")             # from our parser (field 33)

    # Value match: invoice CIF vs SAD invoice value
    if awb_val and sad_inv_val:
        cif_diff_raw = abs(awb_val - sad_inv_val)
        val_match_str = "✓ Verified (±$1.00)" if cif_diff_raw <= 1.0 else f"⚠ Mismatch  Δ {_fmt_usd(cif_diff_raw)}"
    elif awb_val and not sad_inv_val:
        val_match_str = "— SAD value not parsed"
    else:
        val_match_str = "—"

    val = [
        ("Invoice CIF total",        _fmt_usd(awb_val) if awb_val else "(not parsed)"),
        ("AWB customs value",         _fmt_usd(awb_val) + "  (= Invoice CIF)" if awb_val else "(= Invoice CIF)"),
        ("SAD invoice value",         _fmt_usd(sad_inv_val) if sad_inv_val else "(not parsed)"),
        ("Value match status",        val_match_str),
        ("CIF difference (engine)",   _fmt_usd(c5.get("cif_diff", 0)) + "  (tolerance ±$1.00)"),
        ("CIF match",                 _verdict_str(c5.get("cif_result"))),
        ("Statistical value PLN",     _fmt_pln(stat_val) if stat_val else "(not parsed)"),
        ("Duty A00",                  _fmt_pln(c5.get("duty_pln", 0)) + "  ← ZC429/SAD only (never assumed)"),
        ("VAT B00 (reference)",       _fmt_pln(c5.get("vat_pln",  0)) + "  (not in landed cost)"),
        ("NBP rate",                  f"{c5.get('nbp_rate', 0):.4f} USD/PLN  ({c5.get('nbp_table','')} {c5.get('nbp_date','')})"),
        ("SAD customs rate",          f"{c5.get('customs_rate', 0):.4f} USD/PLN  (SAD field 23)" if c5.get("customs_rate") else "(not parsed)"),
        ("Rate delta",                f"{c5.get('rate_delta', 0):.4f}" if c5.get("rate_delta") is not None else "(N/A)"),
    ]
    if goods_desc:
        val.append(("SAD goods desc (field 31)", goods_desc))
    if cn_code:
        val.append(("CN / TARIC (field 33)",     cn_code))
    A(_kv_table(val, S))
    A(Spacer(1, 8))

    # ── Section 5: Freight logic statement ───────────────────────────────────
    A(Paragraph("5. FREIGHT AND INSURANCE ALLOCATION", S["section"]))
    _hr(elems)
    if c5.get("freight_varies"):
        freight_stmt = (
            "Freight and insurance charges vary per invoice and are allocated proportionally "
            "based on each invoice's own CIF structure. No fixed standard amount is applied. "
            "Each line item bears a share of its invoice's transport cost proportional to its "
            "contribution to the invoice's FOB value."
        )
    elif c5.get("has_freight") or c5.get("has_insurance"):
        freight_stmt = (
            "Freight and insurance charges are taken directly from each invoice as stated by "
            "the supplier. Allocated proportionally to line item value within each invoice. "
            "No fixed standard amount applied."
        )
    else:
        freight_stmt = (
            "No freight or insurance charges were found in this invoice set. "
            "CIF value equals FOB value for all invoices."
        )
    A(Paragraph(freight_stmt, S["body"]))
    A(Spacer(1, 8))

    # ── Section 5b: Invoice Quantity Summary ──────────────────────────────────
    pc = inv_totals.get("product_counts", {})
    if inv_totals.get("total_pcs"):
        A(Paragraph("5b. INVOICE QUANTITY SUMMARY", S["section"]))
        _hr(elems)

        qty_rows = [("Total PCS", str(inv_totals["total_pcs"]))]
        _cat_labels = [
            ("rings",           "Rings"),
            ("pendants",        "Pendants"),
            ("bracelets",       "Bracelets"),
            ("earrings",        "Earrings"),
            ("necklaces",       "Necklaces"),
            ("other_jewellery", "Other jewellery"),
        ]
        for key, label in _cat_labels:
            if pc.get(key):
                qty_rows.append((label, str(pc[key])))

        # qty_match_by_type comes from the verification dict; not in audit_data directly.
        # Recompute from SAD total_qty vs invoice total_pcs.
        qty_match_val = None
        if zc429.get("total_qty") and inv_totals.get("total_pcs"):
            inv_pcs  = inv_totals["total_pcs"]
            sad_pcs  = zc429.get("total_qty", 0)
            if isinstance(sad_pcs, (int, float)) and sad_pcs > 0:
                qty_match_val = (abs(inv_pcs - sad_pcs) == 0)

        if qty_match_val is True:
            qty_status = "✓ Verified — invoice PCS matches SAD total"
        elif qty_match_val is False:
            qty_status = f"⚠ Mismatch — invoice {inv_totals['total_pcs']} PCS vs SAD {zc429.get('total_qty')} PCS"
        elif zc429.get("total_qty"):
            qty_status = "Partially verified — SAD gives combined jewellery description"
        else:
            qty_status = "Category split not available in SAD"

        qty_rows.append(("Qty verification", qty_status))
        A(_kv_table(qty_rows, S))
        A(Spacer(1, 8))

    # ── Section 6: Risk assessment ────────────────────────────────────────────
    A(Paragraph("6. RISK ASSESSMENT", S["section"]))
    _hr(elems)

    risk_colour = _RISK_COLOURS.get(risk_level, _AMBER)
    risk_rows = [
        ("Audit score",   f"{score} / 100"),
        ("Risk level",    risk_level),
        ("Failed checks", ", ".join(failed) if failed else "none"),
    ]
    A(_kv_table(risk_rows, S))

    if failed:
        A(Spacer(1, 4))
        A(Paragraph("Issues identified:", S["body_bold"]))
        from escalation import _CHECK_LABELS
        for k in failed:
            A(Paragraph(f"• {_CHECK_LABELS.get(k, k)}", S["body"]))
    A(Spacer(1, 8))

    # ── Section 7: Final statement (bilingual) ────────────────────────────────
    A(Paragraph("7. FINAL STATEMENT", S["section"]))
    _hr(elems)
    A(Paragraph("<b>EN:</b>", S["body_bold"]))
    A(Paragraph(overall_en or "Assessment not available.", S["body"]))
    A(Spacer(1, 5))
    A(Paragraph("<b>PL:</b>", S["body_bold"]))
    A(Paragraph(overall_pl or "Ocena niedostępna.", S["body"]))
    A(Spacer(1, 10))

    # ── Section 7b: Learning intelligence trace ───────────────────────────────
    learning_trace   = audit_data.get("learning_trace", {})
    freight_checks   = audit_data.get("freight_checks", [])
    learning_applied = audit_data.get("learning_applied", False)

    if learning_applied or freight_checks:
        A(Paragraph("7b. LEARNING INTELLIGENCE TRACE", S["section"]))
        _hr(elems)
        A(Paragraph(
            "The following adjustments were applied based on confirmed historical patterns. "
            "Hard-lock checks (value, CIF formula, invoice chain) are never softened by learning.",
            S["body"]
        ))
        A(Spacer(1, 4))

        adj = learning_trace.get("adjustments", {})
        if adj:
            adj_rows = [["Check", "Confidence", "Adjusted", "Reason"]]
            for check_key, info in adj.items():
                if info.get("hard_locked"):
                    continue
                adj_rows.append([
                    check_key,
                    f"{info['confidence']:.0%}" if info.get("adjusted") else "—",
                    "✓" if info.get("adjusted") else "—",
                    Paragraph(info.get("reason", "")[:80], S["body"]),
                ])
            if len(adj_rows) > 1:
                adj_col_w = [42*mm, 18*mm, 14*mm, 76*mm]
                adj_tbl = Table(adj_rows, colWidths=adj_col_w, hAlign="LEFT")
                adj_tbl.setStyle(TableStyle([
                    ("FONTNAME",     (0, 0), (-1, 0), fb),
                    ("FONTSIZE",     (0, 0), (-1, -1), 7.5),
                    ("BACKGROUND",   (0, 0), (-1, 0), _ACCENT),
                    ("TEXTCOLOR",    (0, 0), (-1, 0), colors.white),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _LIGHT]),
                    ("BOX",          (0, 0), (-1, -1), 0.3, _BORDER),
                    ("INNERGRID",    (0, 0), (-1, -1), 0.3, _BORDER),
                    ("TOPPADDING",   (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
                    ("LEFTPADDING",  (0, 0), (-1, -1), 4),
                    ("VALIGN",       (0, 0), (-1, -1), "TOP"),
                ]))
                A(adj_tbl)
                A(Spacer(1, 4))

        if freight_checks:
            A(Paragraph("Freight pattern check (advisory):", S["body_bold"]))
            fr_rows = [["Invoice", "Status", "Actual freight %", "Expected band", "Confidence"]]
            for fc in freight_checks:
                exp = (f"{fc['expected_freight_pct']:.2%} ± {fc.get('tolerance', 0):.2%}"
                       if fc.get("expected_freight_pct") is not None else "—")
                fr_rows.append([
                    fc.get("invoice_no", ""),
                    fc.get("status", ""),
                    f"{fc['actual_freight_pct']:.2%}" if fc.get("actual_freight_pct") is not None else "—",
                    exp,
                    f"{fc['confidence']:.0%}",
                ])
            fr_tbl = Table(fr_rows, colWidths=[48*mm, 28*mm, 24*mm, 36*mm, 14*mm], hAlign="LEFT")
            fr_tbl.setStyle(TableStyle([
                ("FONTNAME",     (0, 0), (-1, 0), fb),
                ("FONTSIZE",     (0, 0), (-1, -1), 7.5),
                ("BACKGROUND",   (0, 0), (-1, 0), _ACCENT),
                ("TEXTCOLOR",    (0, 0), (-1, 0), colors.white),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _LIGHT]),
                ("BOX",          (0, 0), (-1, -1), 0.3, _BORDER),
                ("INNERGRID",    (0, 0), (-1, -1), 0.3, _BORDER),
                ("TOPPADDING",   (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
                ("LEFTPADDING",  (0, 0), (-1, -1), 4),
                ("ALIGN",        (2, 0), (-1, -1), "RIGHT"),
            ]))
            A(fr_tbl)
        A(Spacer(1, 8))

    # ── Section 8: Signature block ────────────────────────────────────────────
    _hr(elems, _ACCENT, 0.8)
    A(Paragraph("8. AUTHORISATION", S["section"]))
    _hr(elems)

    sig_data = [
        [
            Paragraph("<b>Prepared by:</b>", S["body"]),
            Paragraph("Automated Audit Engine v2", S["body"]),
        ],
        [
            Paragraph("<b>Reviewed by:</b>", S["body"]),
            Paragraph("_" * 35, S["body"]),
        ],
        [
            Paragraph("<b>Approved by:</b>", S["body"]),
            Paragraph("_" * 35, S["body"]),
        ],
        [
            Paragraph("<b>Date:</b>", S["body"]),
            Paragraph("_" * 25, S["body"]),
        ],
        [
            Paragraph("<b>Signature:</b>", S["body"]),
            Paragraph("_" * 35, S["body"]),
        ],
    ]
    sig_table = Table(sig_data, colWidths=[55 * mm, 105 * mm], hAlign="LEFT")
    sig_table.setStyle(TableStyle([
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 4),
        ("VALIGN",        (0, 0), (-1, -1), "BOTTOM"),
    ]))
    A(sig_table)
    A(Spacer(1, 10))

    # ── Footer ────────────────────────────────────────────────────────────────
    _hr(elems, _BORDER, 0.3)
    A(Paragraph(
        f"ESTRELLA JEWELS Sp. z o.o. Sp.k. · NIP 5252812119 · "
        f"ul. Wybrzeże Kościuszkowskie 31/33, 00-379 Warszawa · "
        f"Generated {generated} · Batch {batch_id}",
        S["footer"]
    ))

    doc.build(elems)
    return output_path


# ── Text report → PDF converter ───────────────────────────────────────────────

def generate_audit_report_pdf(
    text:        str,
    output_path: Path,
    title:       str = "AUDIT REPORT",
    language:    str = "en",
) -> Path:
    """
    Convert a plain-text audit report (EN or PL) to a PDF with proper Unicode
    font support so Polish characters render correctly.

    Args:
        text:        Full report text (UTF-8).
        output_path: Destination .pdf path.
        title:       Title shown in the header (e.g. "Audit Report — EN").
        language:    "en" or "pl" — used for header label only.

    Returns:
        output_path (Path) after writing.
    """
    output_path = Path(output_path)
    fr, fb = _register_audit_fonts()

    lang_label = "English" if language == "en" else "Polski"
    generated  = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())

    title_style = ParagraphStyle(
        "rpt_title",
        fontName=fb,
        fontSize=12,
        textColor=_DARK,
        alignment=TA_CENTER,
        spaceAfter=2,
    )
    sub_style = ParagraphStyle(
        "rpt_sub",
        fontName=fr,
        fontSize=8,
        textColor=colors.HexColor("#555555"),
        alignment=TA_CENTER,
        spaceAfter=8,
    )
    body_style = ParagraphStyle(
        "rpt_body",
        fontName=fr,
        fontSize=8.5,
        leading=13,
        textColor=_DARK,
        spaceAfter=2,
    )
    section_style = ParagraphStyle(
        "rpt_section",
        fontName=fb,
        fontSize=9.5,
        textColor=_ACCENT,
        spaceBefore=10,
        spaceAfter=4,
    )
    footer_style = ParagraphStyle(
        "rpt_footer",
        fontName=fr,
        fontSize=7,
        textColor=colors.HexColor("#888888"),
        alignment=TA_CENTER,
    )

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=16 * mm,
        bottomMargin=20 * mm,
    )

    elems: list = []
    A = elems.append

    A(Paragraph(f"ESTRELLA JEWELS Sp. z o.o. Sp.k.", title_style))
    A(Paragraph(f"{title} — {lang_label}", title_style))
    _hr(elems, _ACCENT, 1.0)
    A(Paragraph(f"Generated {generated}", sub_style))

    # Parse the text into lines; detect section headers (ALL-CAPS lines or
    # lines ending with ":" that look like headers) and render them differently.
    def _is_section_header(line: str) -> bool:
        stripped = line.strip()
        if not stripped:
            return False
        # Lines like "=== SECTION ===" or "--- HEADING ---"
        if stripped.startswith(("===", "---", "***")):
            return True
        # All-uppercase lines of ≥ 4 chars (e.g. "EXPORTER", "VALUE RECONCILIATION")
        letters = [c for c in stripped if c.isalpha()]
        if letters and len(letters) >= 4 and all(c.isupper() for c in letters):
            return True
        return False

    for raw_line in text.splitlines():
        line = raw_line.rstrip()

        # Blank line → small spacer
        if not line.strip():
            A(Spacer(1, 4))
            continue

        # Separator lines → horizontal rule
        if set(line.strip()) <= set("=-*_"):
            _hr(elems, _BORDER, 0.3)
            continue

        if _is_section_header(line):
            A(Paragraph(line.strip("=- *"), section_style))
        else:
            # Escape XML-special chars for ReportLab Paragraph
            safe = (line
                    .replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;"))
            A(Paragraph(safe, body_style))

    _hr(elems, _BORDER, 0.3)
    A(Paragraph(
        f"ESTRELLA JEWELS Sp. z o.o. Sp.k. · NIP 5252812119 · "
        f"ul. Wybrzeże Kościuszkowskie 31/33, 00-379 Warszawa · "
        f"Generated {generated}",
        footer_style,
    ))

    doc.build(elems)
    return output_path
