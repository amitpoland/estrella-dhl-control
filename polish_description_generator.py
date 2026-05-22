"""
polish_description_generator.py — Polish Customs Goods Description PDF Generator.

Generates a PDF with a customs goods description in DHL's required format.
One block per unique item type (consolidated across all invoices in the batch).

Uses reportlab for A4 PDF generation.
Filename: POLISH_DESC_{AWB_CLEAN}_{DATE}.pdf

This module covers ONLY goods descriptions — not invoice totals, banking,
or legal text.
"""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ── Service-side description engine (single source of truth) ─────────────────
# When the service path is reachable we read locked description blocks from
# description_engine. The engine persists per-product_code blocks and honors
# manual overrides; we pass item_type as the lookup key here because this
# generator consolidates by type. Falls back to in-module ITEM_TRANSLATIONS
# when the service module is not importable (e.g. CLI invocation outside the
# service venv) or when document_db has not been initialised.

def _try_load_description_engine():
    _svc = os.path.join(os.path.dirname(__file__), "service")
    if _svc not in sys.path:
        sys.path.insert(0, _svc)
    try:
        from app.services import description_engine as _eng  # type: ignore
        return _eng
    except Exception:
        return None


_DESCRIPTION_ENGINE = _try_load_description_engine()


# ── Item type translations ────────────────────────────────────────────────────

# Mapping from plural lowercase keys used in invoice_totals.product_counts_by_unit
# to canonical ITEM_TRANSLATIONS keys.
_PLURAL_TO_CANONICAL: dict[str, str] = {
    "rings":           "RING",
    "pendants":        "PENDANT",
    "earrings":        "EARRINGS",
    "bracelets":       "BRACELET",
    "necklaces":       "NECKLACE",
    "cufflinks":       "CUFFLINK",
    "anklets":         "ANKLET",
    "bangles":         "BANGLE",
    "sets":            "SET",
    "other_jewellery": "OTHER",
}

ITEM_TRANSLATIONS: dict[str, dict] = {
    "EARRINGS": {
        "name_pl":        "Kolczyki",
        "description_pl": "Biżuteria — kolczyki",
        "material_pl":    "Metal (srebro/stop metali) z kamieniami ozdobnymi",
        "purpose_pl":     "Ozdoba noszona na uszach",
    },
    "EARRING": {
        "name_pl":        "Kolczyki",
        "description_pl": "Biżuteria — kolczyki",
        "material_pl":    "Metal (srebro/stop metali) z kamieniami ozdobnymi",
        "purpose_pl":     "Ozdoba noszona na uszach",
    },
    "PENDANT": {
        "name_pl":        "Wisiorek",
        "description_pl": "Biżuteria — wisiorek",
        "material_pl":    "Metal (srebro/stop metali) z kamieniami ozdobnymi",
        "purpose_pl":     "Ozdoba noszona na szyi",
    },
    "RING": {
        "name_pl":        "Pierścionek",
        "description_pl": "Biżuteria — pierścionek",
        "material_pl":    "Metal (srebro/stop metali) z kamieniami ozdobnymi",
        "purpose_pl":     "Ozdoba noszona na palcu",
    },
    "BRACELET": {
        "name_pl":        "Bransoletka",
        "description_pl": "Biżuteria — bransoletka",
        "material_pl":    "Metal (srebro/stop metali) z kamieniami ozdobnymi",
        "purpose_pl":     "Ozdoba noszona na nadgarstku",
    },
    "NECKLACE": {
        "name_pl":        "Naszyjnik",
        "description_pl": "Biżuteria — naszyjnik",
        "material_pl":    "Metal (srebro/stop metali) z kamieniami ozdobnymi",
        "purpose_pl":     "Ozdoba noszona na szyi",
    },
    "BANGLE": {
        "name_pl":        "Bransoletka sztywna",
        "description_pl": "Biżuteria — bransoletka sztywna",
        "material_pl":    "Metal (srebro/stop metali) z kamieniami ozdobnymi",
        "purpose_pl":     "Ozdoba noszona na nadgarstku",
    },
    "ANKLET": {
        "name_pl":        "Bransoletka nożna",
        "description_pl": "Biżuteria — bransoletka nożna",
        "material_pl":    "Metal (srebro/stop metali) z kamieniami ozdobnymi",
        "purpose_pl":     "Ozdoba noszona na kostce",
    },
    "SET": {
        "name_pl":        "Komplet biżuterii",
        "description_pl": "Komplet biżuterii (kolczyki + wisiorek lub inne elementy)",
        "material_pl":    "Metal (srebro/stop metali) z kamieniami ozdobnymi",
        "purpose_pl":     "Ozdoba — komplet",
    },
    "CUFFLINK": {
        "name_pl":        "Spinki do mankietów",
        "description_pl": "Biżuteria — spinki do mankietów",
        "material_pl":    "Metal (srebro/stop metali) z kamieniami ozdobnymi",
        "purpose_pl":     "Ozdoba — spinki do mankietów",
    },
}

DEFAULT_TRANSLATION: dict = {
    "name_pl":        "Biżuteria",
    "description_pl": "Wyrób jubilerski",
    "material_pl":    "Metal z kamieniami ozdobnymi",
    "purpose_pl":     "Ozdoba",
}

# ── Company info ──────────────────────────────────────────────────────────────

RECIPIENT_NAME = "ESTRELLA JEWELS SP. Z O. O. SP. K."
FOOTER_TEXT    = (
    "Dokument wygenerowany automatycznie przez system PZ Estrella Jewels."
)


# ── Public API ────────────────────────────────────────────────────────────────

def generate_polish_description(
    batch: dict,
    awb: str,
    output_dir: str,
    date_override: Optional[str] = None,
) -> dict:
    """
    Generate a Polish customs goods description PDF.

    Parameters
    ----------
    batch         : batch audit dict (from audit.json or process_batch result)
    awb           : AWB number (used in filename and header)
    output_dir    : directory where the PDF is saved
    date_override : date string (YYYY-MM-DD); defaults to today

    Returns
    -------
    dict with keys:
        generated       : bool
        output_path     : str | None
        filename        : str | None
        items_described : int
        error           : str | None
    """
    try:
        return _generate(batch, awb, output_dir, date_override)
    except Exception as exc:
        return {
            "generated":       False,
            "output_path":     None,
            "filename":        None,
            "items_described": 0,
            "error":           str(exc),
        }


# ── Internal implementation ───────────────────────────────────────────────────

def _generate(
    batch: dict,
    awb: str,
    output_dir: str,
    date_override: Optional[str],
) -> dict:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
    )
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    # ── Register Unicode font for Polish character support ────────────────────
    _FONT_PATHS = [
        # Windows (production server) — listed first because production runs
        # on Windows; without these paths Polish diacritics (ś, ż, ą, ę, ł,
        # ć, ń, ó, ź) render as ■ (U+25A0) via the Helvetica fallback.
        'C:/Windows/Fonts/arial.ttf',
        'C:/Windows/Fonts/segoeui.ttf',
        'C:/Windows/Fonts/calibri.ttf',
        'C:/Windows/Fonts/tahoma.ttf',
        # macOS (developer machines)
        '/Library/Fonts/Arial Unicode.ttf',
        '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
        # Linux (CI / containers)
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/freefont/FreeSans.ttf',
    ]
    _FONT_REG = 'Helvetica'   # fallback if no Unicode font found
    _FONT_BOLD = 'Helvetica-Bold'
    for _fp in _FONT_PATHS:
        if Path(_fp).exists():
            try:
                pdfmetrics.registerFont(TTFont('UniFont', _fp))
                _FONT_REG = 'UniFont'
                _FONT_BOLD = 'UniFont'
            except Exception:
                pass
            break

    # ── Prepare metadata ──────────────────────────────────────────────────────
    awb_clean = re.sub(r"\s+", "", awb)
    today     = date_override or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    date_pl   = _format_date_pl(today)

    filename   = f"POLISH_DESC_{awb_clean}_{today.replace('-', '')}.pdf"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = str(output_dir / filename)

    # ── Extract items, invoice refs, and financial summary from batch ─────────
    items        = _extract_items(batch)
    consolidated = _consolidate_by_type(items)
    invoice_refs = _extract_invoice_refs(batch)
    fin          = _extract_financial_summary(batch)

    # ── Build exporter name ───────────────────────────────────────────────────
    exporter = _get_exporter(batch)

    # ── Styles ────────────────────────────────────────────────────────────────
    styles = getSampleStyleSheet()

    style_h1 = ParagraphStyle(
        "H1",
        parent=styles["Heading1"],
        fontSize=14,
        leading=18,
        spaceAfter=4,
        textColor=colors.HexColor("#1e293b"),
        fontName=_FONT_BOLD,
    )
    style_h2 = ParagraphStyle(
        "H2",
        parent=styles["Heading2"],
        fontSize=11,
        leading=14,
        spaceBefore=12,
        spaceAfter=2,
        textColor=colors.HexColor("#0f172a"),
        fontName=_FONT_BOLD,
    )
    style_body = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontSize=9,
        leading=13,
        fontName=_FONT_REG,
        textColor=colors.HexColor("#334155"),
    )
    style_label = ParagraphStyle(
        "Label",
        parent=styles["Normal"],
        fontSize=8,
        leading=11,
        fontName=_FONT_BOLD,
        textColor=colors.HexColor("#64748b"),
        spaceAfter=1,
    )
    style_section = ParagraphStyle(
        "Section",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
        spaceBefore=10,
        spaceAfter=4,
        fontName=_FONT_BOLD,
        textColor=colors.HexColor("#475569"),
        borderPad=0,
    )
    style_footer = ParagraphStyle(
        "Footer",
        parent=styles["Normal"],
        fontSize=7,
        leading=10,
        fontName=_FONT_REG,
        textColor=colors.HexColor("#94a3b8"),
        alignment=1,   # center
    )

    # ── Build document ────────────────────────────────────────────────────────
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Opis Towarów — AWB {awb_clean}",
        author="Estrella Jewels Sp. z o.o. Sp. k.",
        subject="Opis towarów do odprawy celnej",
    )

    story = []

    # ── Header ────────────────────────────────────────────────────────────────
    story.append(Paragraph("OPIS TOWARÓW DO ODPRAWY CELNEJ", style_h1))
    story.append(HRFlowable(width="100%", thickness=1,
                             color=colors.HexColor("#e2e8f0"), spaceAfter=8))

    header_data = [
        ["AWB / Air Waybill:",      awb_clean],
        ["Data / Date:",            date_pl],
        ["Nadawca / Shipper:",      exporter or "Estrella Jewels LLP."],
        ["Odbiorca / Consignee:",   RECIPIENT_NAME],
    ]
    header_table = Table(header_data, colWidths=[50 * mm, None])
    header_table.setStyle(TableStyle([
        ("FONTNAME",  (0, 0), (0, -1), _FONT_BOLD),
        ("FONTNAME",  (1, 0), (1, -1), _FONT_REG),
        ("FONTSIZE",  (0, 0), (-1, -1), 9),
        ("LEADING",   (0, 0), (-1, -1), 13),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#475569")),
        ("TEXTCOLOR", (1, 0), (1, -1), colors.HexColor("#0f172a")),
        ("VALIGN",    (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING",    (0, 0), (-1, -1), 1),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 6 * mm))

    # ── Invoice references ────────────────────────────────────────────────────
    if invoice_refs:
        story.append(Paragraph(
            "FAKTURY / INVOICES", style_section,
        ))
        story.append(HRFlowable(width="100%", thickness=0.5,
                                 color=colors.HexColor("#cbd5e1"), spaceAfter=4))
        inv_rows = [["Nr", "Nr faktury / Invoice No."]]
        for i, ref in enumerate(invoice_refs, start=1):
            inv_rows.append([str(i), ref])
        inv_table = Table(inv_rows, colWidths=[12 * mm, None])
        inv_table.setStyle(TableStyle([
            ("FONTNAME",  (0, 0), (-1, 0),  _FONT_BOLD),
            ("FONTNAME",  (0, 1), (-1, -1), _FONT_REG),
            ("FONTSIZE",  (0, 0), (-1, -1), 8),
            ("LEADING",   (0, 0), (-1, -1), 12),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
            ("TEXTCOLOR", (0, 0), (-1, 0),  colors.HexColor("#475569")),
            ("TEXTCOLOR", (0, 1), (-1, -1), colors.HexColor("#1e293b")),
            ("GRID",      (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
            ("VALIGN",    (0, 0), (-1, -1), "MIDDLE"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ]))
        story.append(inv_table)
        story.append(Spacer(1, 5 * mm))

    # ── Item blocks ───────────────────────────────────────────────────────────
    story.append(Paragraph(
        "OPIS TOWARÓW / GOODS DESCRIPTION", style_section,
    ))
    story.append(HRFlowable(width="100%", thickness=0.5,
                             color=colors.HexColor("#cbd5e1"), spaceAfter=4))

    if not consolidated:
        story.append(Paragraph("Brak pozycji towarowych.", style_body))
    else:
        for idx, item in enumerate(consolidated, start=1):
            trans   = item["translation"]
            qty     = item["qty_total"]
            unit    = item.get("unit", "PCS")
            it_type = item["item_type"]

            # Pull the locked block from description_engine when available.
            block = None
            if _DESCRIPTION_ENGINE is not None:
                try:
                    block = _DESCRIPTION_ENGINE.get_description_block(
                        product_code   = it_type,
                        item_type      = it_type,
                        description_en = it_type,
                    )
                except Exception:
                    block = None

            name_pl        = (block or trans).get("name_pl", trans["name_pl"])
            description_pl = (block or trans).get("description_pl", trans["description_pl"])
            material_pl    = (block or trans).get("material_pl", trans["material_pl"])
            purpose_pl     = (block or trans).get("purpose_pl", trans["purpose_pl"])
            description_en = (block or {}).get("description_en", it_type)
            description_line = (block or {}).get("description_line") or (
                f"{description_pl} / {description_en}"
                if description_en else description_pl
            )

            qty_display = (f"{qty:.0f}" if qty == int(qty) else f"{qty}") + f" {unit}"

            story.append(Paragraph(
                f"Pozycja {idx}: {name_pl} ({it_type})",
                style_h2,
            ))

            item_data = [
                ["Co to za towar / Description:",  description_line],
                ["Z jakiego materiału / Material:", material_pl],
                ["Do czego służy / Purpose:",       purpose_pl],
                ["Ilość / Quantity:",                qty_display],
            ]
            item_table = Table(item_data, colWidths=[65 * mm, None])
            item_table.setStyle(TableStyle([
                ("FONTNAME",  (0, 0), (0, -1), _FONT_BOLD),
                ("FONTNAME",  (1, 0), (1, -1), _FONT_REG),
                ("FONTSIZE",  (0, 0), (-1, -1), 9),
                ("LEADING",   (0, 0), (-1, -1), 13),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#475569")),
                ("TEXTCOLOR", (1, 0), (1, -1), colors.HexColor("#1e293b")),
                ("VALIGN",    (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING",    (0, 0), (-1, -1), 1),
                ("ROWBACKGROUNDS", (0, 0), (-1, -1),
                    [colors.HexColor("#f8fafc"), colors.white]),
            ]))
            story.append(item_table)

            if idx < len(consolidated):
                story.append(HRFlowable(
                    width="100%", thickness=0.5,
                    color=colors.HexColor("#e2e8f0"),
                    spaceAfter=4, spaceBefore=4,
                ))

    # ── Financial summary ─────────────────────────────────────────────────────
    if fin:
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph(
            "PODSUMOWANIE FINANSOWE / FINANCIAL SUMMARY", style_section,
        ))
        story.append(HRFlowable(width="100%", thickness=0.5,
                                 color=colors.HexColor("#cbd5e1"), spaceAfter=4))

        fin_data = [
            ["Wartość FOB / FOB Value:",               _fmt_usd(fin["fob"])],
            ["Fracht / Freight:",                       _fmt_usd(fin["freight"])],
            ["Ubezpieczenie / Insurance:",              _fmt_usd(fin["insurance"])],
            ["RAZEM CIF / TOTAL CIF (customs value):", _fmt_usd(fin["cif"])],
        ]
        fin_table = Table(fin_data, colWidths=[100 * mm, None])
        fin_table.setStyle(TableStyle([
            ("FONTNAME",  (0, 0),  (0, -1), _FONT_REG),
            ("FONTNAME",  (1, 0),  (1, -1), _FONT_REG),
            ("FONTNAME",  (0, -1), (1, -1), _FONT_BOLD),   # CIF row bold
            ("FONTSIZE",  (0, 0),  (-1, -1), 9),
            ("LEADING",   (0, 0),  (-1, -1), 13),
            ("TEXTCOLOR", (0, 0),  (0, -1), colors.HexColor("#475569")),
            ("TEXTCOLOR", (1, 0),  (1, -2), colors.HexColor("#1e293b")),
            ("TEXTCOLOR", (0, -1), (1, -1), colors.HexColor("#0f172a")),
            ("BACKGROUND", (0, -1), (1, -1), colors.HexColor("#f1f5f9")),
            ("LINEABOVE",  (0, -1), (1, -1), 0.8, colors.HexColor("#94a3b8")),
            ("ALIGN",      (1, 0),  (1, -1), "RIGHT"),
            ("VALIGN",     (0, 0),  (-1, -1), "MIDDLE"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ]))
        story.append(fin_table)

    # ── Footer ────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 12 * mm))
    story.append(HRFlowable(width="100%", thickness=0.5,
                             color=colors.HexColor("#e2e8f0"), spaceAfter=6))
    story.append(Paragraph(FOOTER_TEXT, style_footer))

    # ── Build PDF ─────────────────────────────────────────────────────────────
    doc.build(story)

    return {
        "generated":       True,
        "output_path":     output_path,
        "filename":        filename,
        "items_described": len(consolidated),
        "error":           None,
    }


def _extract_items(batch: dict) -> list[dict]:
    """
    Extract item rows from a batch audit dict.
    Looks in: result.rows, rows, invoices[].items, invoice_totals.product_counts_by_unit.
    Each returned dict has at minimum: item_type, qty.
    Optional key: unit (e.g. "PCS", "PRS").
    """
    rows = []

    # Try result.rows (process_batch output stored in audit)
    result = batch.get("result") or batch
    if isinstance(result, dict):
        batch_rows = result.get("rows", [])
        if isinstance(batch_rows, list):
            rows = batch_rows

    # Try invoices[].items as fallback
    if not rows:
        invoices = (batch.get("invoices") or
                    (batch.get("result") or {}).get("invoices") or [])
        for inv in (invoices or []):
            for item in (inv.get("items") or []):
                rows.append(item)

    # Final fallback: invoice_totals.product_counts_by_unit
    # Format: {"PCS": {"rings": 5, "pendants": 2}, "PRS": {"earrings": 4}}
    if not rows:
        it = batch.get("invoice_totals") or {}
        pcu = it.get("product_counts_by_unit") or {}
        for unit, type_counts in pcu.items():
            for raw_type, qty in (type_counts or {}).items():
                if not qty or qty <= 0:
                    continue
                canonical = _PLURAL_TO_CANONICAL.get(raw_type.lower(), raw_type.upper())
                rows.append({
                    "item_type": canonical,
                    "qty":       qty,
                    "unit":      unit,
                })

    return rows


def _consolidate_by_type(rows: list[dict]) -> list[dict]:
    """
    Merge all rows by item_type. Sum quantities.
    Returns list of dicts: {item_type, qty_total, unit, translation}
    """
    from collections import defaultdict

    totals: dict[str, float] = defaultdict(float)
    units: dict[str, str] = {}

    for row in rows:
        item_type = (
            row.get("item_type") or
            row.get("type") or
            ""
        ).upper().strip()
        if not item_type:
            continue

        qty = 0.0
        for qty_key in ("qty", "quantity", "line_qty"):
            v = row.get(qty_key)
            if v is not None:
                try:
                    qty = float(v)
                    break
                except (ValueError, TypeError):
                    pass

        totals[item_type] += qty
        if item_type not in units and row.get("unit"):
            units[item_type] = row["unit"]

    consolidated = []
    for item_type, qty_total in totals.items():
        trans = ITEM_TRANSLATIONS.get(item_type, DEFAULT_TRANSLATION)
        consolidated.append({
            "item_type":   item_type,
            "qty_total":   qty_total,
            "unit":        units.get(item_type, "PCS"),
            "translation": trans,
        })

    # Sort by item type name for deterministic output
    consolidated.sort(key=lambda x: x["item_type"])
    return consolidated


def _extract_invoice_refs(batch: dict) -> list[str]:
    """
    Return a sorted list of invoice reference strings from invoice_names.
    E.g. ["121 Invoice EJL-26-27-121-04-05-26.pdf", ...] → ["121", "122", "123", "124"]
    Falls back to invoice filenames if no leading numeric token found.
    """
    names = batch.get("invoice_names") or []
    refs = []
    for name in names:
        stem = Path(name).stem   # strip .pdf
        token = stem.split()[0] if stem.split() else stem
        if re.match(r"^\d+$", token):
            refs.append(token)
        else:
            refs.append(stem[:40])   # truncate long names
    return refs


def _extract_financial_summary(batch: dict) -> dict | None:
    """
    Return {fob, freight, insurance, cif} in USD from invoice_totals.
    Returns None if no financial data is available.
    """
    it = batch.get("invoice_totals") or {}
    fob       = it.get("total_fob_usd")
    freight   = it.get("total_freight_usd")
    insurance = it.get("total_insurance_usd")
    cif       = it.get("total_cif_usd")
    if cif is None:
        return None
    return {
        "fob":       fob or 0.0,
        "freight":   freight or 0.0,
        "insurance": insurance or 0.0,
        "cif":       cif,
    }


def _fmt_usd(value: float) -> str:
    """Format a USD amount with comma-separated thousands and 2 decimals."""
    return f"{value:,.2f} USD"


def _get_exporter(batch: dict) -> str:
    """Extract exporter/seller name from batch dict."""
    # Try invoices
    invoices = (
        (batch.get("result") or {}).get("invoices") or
        batch.get("invoices") or []
    )
    if invoices:
        inv = invoices[0]
        for key in ("exporter_name", "seller_name", "supplier_name"):
            v = inv.get(key)
            if v:
                return str(v)

    # Try zc429
    zc429 = (batch.get("result") or {}).get("zc429") or batch.get("zc429") or {}
    if isinstance(zc429, dict):
        v = zc429.get("exporter_name") or zc429.get("seller")
        if v:
            return str(v)

    return ""


def _format_date_pl(iso_date: str) -> str:
    """Convert YYYY-MM-DD to DD.MM.YYYY."""
    try:
        d = datetime.strptime(iso_date, "%Y-%m-%d")
        return d.strftime("%d.%m.%Y")
    except ValueError:
        return iso_date


# ── Quick smoke test ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import tempfile
    import json

    print("=== Polish Description Generator — self-test ===\n")

    fake_batch = {
        "rows": [
            {"item_type": "EARRINGS",  "qty": 10},
            {"item_type": "PENDANT",   "qty": 5},
            {"item_type": "RING",      "qty": 8},
            {"item_type": "BRACELET",  "qty": 3},
            {"item_type": "EARRINGS",  "qty": 4},   # should merge with first
        ],
        "invoices": [
            {"exporter_name": "Estrella Jewels LLP."},
        ],
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        result = generate_polish_description(
            batch          = fake_batch,
            awb            = "3283625844",
            output_dir     = tmpdir,
            date_override  = "2026-04-26",
        )
        print(json.dumps(result, indent=2))
        if result["generated"]:
            size = os.path.getsize(result["output_path"])
            print(f"\nOutput: {result['output_path']}")
            print(f"Size:   {size:,} bytes")
            print(f"Items:  {result['items_described']}")

    print("\n=== Done ===")
