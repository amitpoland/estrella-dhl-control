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
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Item type translations ────────────────────────────────────────────────────

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
        '/Library/Fonts/Arial Unicode.ttf',
        '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
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

    # ── Extract items from batch ──────────────────────────────────────────────
    items = _extract_items(batch)
    consolidated = _consolidate_by_type(items)

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
        ["AWB:", awb_clean],
        ["Data:", date_pl],
        ["Nadawca:", exporter or "Estrella Jewels LLP."],
        ["Odbiorca:", RECIPIENT_NAME],
    ]
    header_table = Table(header_data, colWidths=[35 * mm, None])
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
    story.append(Spacer(1, 10 * mm))

    # ── Item blocks ───────────────────────────────────────────────────────────
    if not consolidated:
        story.append(Paragraph("Brak pozycji towarowych.", style_body))
    else:
        for idx, item in enumerate(consolidated, start=1):
            trans = item["translation"]
            qty   = item["qty_total"]

            story.append(Paragraph(
                f"Pozycja {idx}: {trans['name_pl']} ({item['item_type']})",
                style_h2,
            ))

            item_data = [
                ["Co to za towar:",          trans["description_pl"]],
                ["Z jakiego materiału:",     trans["material_pl"]],
                ["Do czego służy:",          trans["purpose_pl"]],
                ["Ilość:",                   f"{qty:.0f}" if qty == int(qty) else f"{qty}"],
            ]
            item_table = Table(item_data, colWidths=[55 * mm, None])
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
    Looks in: result.rows, rows, invoices[].items
    Each returned dict has at minimum: item_type, qty.
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

    return rows


def _consolidate_by_type(rows: list[dict]) -> list[dict]:
    """
    Merge all rows by item_type. Sum quantities.
    Returns list of dicts: {item_type, qty_total, translation}
    """
    from collections import defaultdict

    totals: dict[str, float] = defaultdict(float)

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

    consolidated = []
    for item_type, qty_total in totals.items():
        trans = ITEM_TRANSLATIONS.get(item_type, DEFAULT_TRANSLATION)
        consolidated.append({
            "item_type":   item_type,
            "qty_total":   qty_total,
            "translation": trans,
        })

    # Sort by item type name for deterministic output
    consolidated.sort(key=lambda x: x["item_type"])
    return consolidated


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
