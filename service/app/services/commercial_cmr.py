"""
commercial_cmr.py — ONE CMR / delivery-note document authority for server export.

Canonical model mirrors Proforma ``cmrPreviewData`` → ``EJCMRClassic`` /
``EJCMRModern`` (browser preview). Preview remains React; this module is the
PDF/export adapter over the same business facts — not a second CMR template
with different lines/weights/parties.

CMR is NOT a customer-send whitelist document. Attachments are used only by
delivery_confirmation when a CMR number exists for the linked outbound shipment.
"""
from __future__ import annotations

import io
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

_ISO2_COUNTRY = {
    "PL": "Poland", "DE": "Germany", "FR": "France", "IT": "Italy",
    "ES": "Spain", "NL": "Netherlands", "BE": "Belgium", "AT": "Austria",
    "CZ": "Czech Republic", "SK": "Slovakia", "HU": "Hungary", "RO": "Romania",
    "BG": "Bulgaria", "HR": "Croatia", "SI": "Slovenia", "LT": "Lithuania",
    "LV": "Latvia", "EE": "Estonia", "SE": "Sweden", "DK": "Denmark",
    "FI": "Finland", "IE": "Ireland", "PT": "Portugal", "GR": "Greece",
    "IN": "India", "CN": "China", "US": "United States", "GB": "United Kingdom",
    "CH": "Switzerland", "NO": "Norway", "UA": "Ukraine",
}


def _country_name(code_or_name: Optional[str]) -> Optional[str]:
    raw = (code_or_name or "").strip()
    if not raw or raw == "—":
        return None
    up = raw.upper()
    if len(up) == 2 and up in _ISO2_COUNTRY:
        return _ISO2_COUNTRY[up]
    return raw


def _item_category_label(item_type: str) -> str:
    try:
        import sys
        root = str(Path(__file__).resolve().parents[3])
        if root not in sys.path:
            sys.path.insert(0, root)
        from description_grammar import ITEM_TYPE_EN, canonical_item_type
        key = canonical_item_type(item_type or "")
        if key and key in ITEM_TYPE_EN:
            return ITEM_TYPE_EN[key]
    except Exception:
        pass
    return (item_type or "").strip() or "Goods"


def _party_from_company(company: Any) -> Dict[str, str]:
    if company is None:
        return {"name": "", "addr": "", "city": "", "vat": "", "email": "", "phone": ""}
    return {
        "name": getattr(company, "legal_name", None) or "",
        "addr": getattr(company, "street", None) or "",
        "city": getattr(company, "postal_city", None) or "",
        "vat": getattr(company, "vat_eu", None) or getattr(company, "nip", None) or "",
        "email": getattr(company, "email", None) or "",
        "phone": getattr(company, "phone", None) or "",
    }


def _buyer_shipto(customer: Any) -> Tuple[Dict[str, str], Dict[str, str]]:
    buyer = {"vat": ""}
    shipto = {"name": "", "addr": "", "city": "", "zip": "", "country": ""}
    if customer is None:
        return buyer, shipto
    try:
        from .customer_master import resolve_billing_address, resolve_delivery_address
        bill = resolve_billing_address(customer) or {}
        deliv = resolve_delivery_address(customer) or {}
        buyer = {"vat": getattr(customer, "vat_number", None) or bill.get("vat") or ""}
        shipto = {
            "name": deliv.get("name") or bill.get("name") or getattr(customer, "name", None) or "",
            "addr": deliv.get("street") or bill.get("street") or "",
            "city": deliv.get("city") or bill.get("city") or "",
            "zip": deliv.get("postal_code") or bill.get("postal_code") or "",
            "country": deliv.get("country") or bill.get("country") or "",
        }
    except Exception as exc:
        log.debug("cmr customer resolve failed: %s", exc)
    return buyer, shipto


def _aggregate_lines(raw_lines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Transport summary rows: aggregate by item_type (same as cmrPreviewData)."""
    buckets: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for ln in raw_lines:
        label = _item_category_label(str(ln.get("item_type") or ""))
        key = label or "Goods"
        if key not in buckets:
            buckets[key] = {
                "item_type": key,
                "qty": 0.0,
                "net_weight": 0.0,
                "origin": None,
                "_origins": set(),
            }
            order.append(key)
        b = buckets[key]
        try:
            b["qty"] += float(ln.get("qty") or ln.get("quantity") or 0)
        except (TypeError, ValueError):
            pass
        try:
            nw = float(ln.get("net_weight") or 0)
            if nw > 0:
                b["net_weight"] += nw
        except (TypeError, ValueError):
            pass
        origin = _country_name(str(ln.get("origin") or "").strip() or None)
        if origin:
            b["_origins"].add(origin)
    out: List[Dict[str, Any]] = []
    for key in order:
        b = buckets[key]
        origins = sorted(b.pop("_origins"))
        qty = b["qty"]
        nw = b["net_weight"]
        out.append({
            "item_type": b["item_type"],
            "qty": int(qty) if qty == int(qty) else qty,
            "net_weight": nw if nw > 0 else None,
            "origin": " / ".join(origins) if origins else None,
        })
    return out


def build_cmr_document(
    *,
    draft: Any,
    storage_root: Path,
    company: Any = None,
    customer: Any = None,
    shipment_row: Optional[Dict[str, Any]] = None,
    cmr_number: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the canonical CMR document model (cmrPreviewData shape)."""
    raw_lines: List[Dict[str, Any]] = []
    if draft is not None:
        try:
            raw = getattr(draft, "editable_lines_json", None)
            if raw:
                parsed = json.loads(raw) if isinstance(raw, str) else raw
                raw_lines = list(parsed or [])
        except Exception as exc:
            log.warning("cmr: editable_lines parse failed: %s", exc)

    # Physical weight enrich (same commercial_authority path packing uses).
    batch_id = ""
    if draft is not None:
        batch_id = str(getattr(draft, "batch_id", None) or "")
    try:
        from .commercial_authority import attach_physical_weights_to_lines
        raw_lines = attach_physical_weights_to_lines(batch_id or "", list(raw_lines))
    except Exception as exc:
        log.debug("cmr physical-weight enrich failed: %s", exc)

    lines = _aggregate_lines(raw_lines)
    seller = _party_from_company(company)
    buyer, shipto = _buyer_shipto(customer)

    awb = None
    carrier_name = None
    service = None
    weight_kg = None
    if shipment_row:
        awb = (shipment_row.get("tracking_ref") or "").strip() or None
        carrier_name = (shipment_row.get("provider") or shipment_row.get("carrier") or "DHL")
        service = shipment_row.get("service_product") or shipment_row.get("service")
        try:
            weight_kg = float(shipment_row.get("weight_kg") or 0) or None
        except (TypeError, ValueError):
            weight_kg = None

    total_pcs = sum(float(l.get("qty") or 0) for l in lines) or None
    doc_ref = ""
    if draft is not None:
        doc_ref = (
            getattr(draft, "wfirma_proforma_fullnumber", None)
            or getattr(draft, "wfirma_proforma_id", None)
            or ""
        )

    carrier = None
    if awb:
        carrier = {
            "name": str(carrier_name or "DHL"),
            "awb": awb,
            "service": service or "—",
            "origin": seller.get("city") or "—",
            "destination": shipto.get("city") or shipto.get("country") or "—",
            "pieces": int(total_pcs) if total_pcs else None,
            "weight_kg": weight_kg,
        }

    origins = sorted({
        o for l in lines for o in [l.get("origin")] if o
    })
    return {
        "authority": "commercial_cmr",
        "cmr_no": cmr_number,
        "doc_ref": doc_ref or "—",
        "batch_ref": batch_id or None,
        "seller": seller,
        "shipto": shipto,
        "buyer": buyer,
        "carrier": carrier,
        "lines": lines,
        "goods_summary": "",
        "goods_origin_country": " / ".join(origins) if origins else None,
    }


def render_cmr_pdf(document: Dict[str, Any]) -> bytes:
    """PDF presentation adapter over ``build_cmr_document`` (Modern CMR layout)."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.units import mm
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
        )
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        import reportlab as _rl
    except ImportError as exc:
        raise RuntimeError(f"ReportLab unavailable: {exc}") from exc

    font, font_bold = "Helvetica", "Helvetica-Bold"
    try:
        reg_name, bold_name = "EJCMR", "EJCMR-Bold"
        if reg_name not in pdfmetrics.getRegisteredFontNames():
            _rl_font_dir = os.path.join(os.path.dirname(_rl.__file__), "fonts")
            for reg, bold in (
                (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\arialbd.ttf"),
                (os.path.join(_rl_font_dir, "Vera.ttf"), os.path.join(_rl_font_dir, "VeraBd.ttf")),
            ):
                if os.path.exists(reg) and os.path.exists(bold):
                    pdfmetrics.registerFont(TTFont(reg_name, reg))
                    pdfmetrics.registerFont(TTFont(bold_name, bold))
                    font, font_bold = reg_name, bold_name
                    break
        else:
            font, font_bold = reg_name, bold_name
    except Exception:
        pass

    styles = getSampleStyleSheet()
    H1 = ParagraphStyle("CMRH1", parent=styles["Normal"], fontName=font_bold, fontSize=14, leading=18)
    H2 = ParagraphStyle("CMRH2", parent=styles["Normal"], fontName=font_bold, fontSize=9, leading=12)
    TXT = ParagraphStyle("CMRTXT", parent=styles["Normal"], fontName=font, fontSize=8.5, leading=11)
    SML = ParagraphStyle("CMRSML", parent=styles["Normal"], fontName=font, fontSize=7.5, leading=10,
                         textColor=colors.HexColor("#555555"))

    d = document or {}
    seller = d.get("seller") or {}
    shipto = d.get("shipto") or {}
    buyer = d.get("buyer") or {}
    carrier = d.get("carrier") or {}
    lines = d.get("lines") or []

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=14 * mm, rightMargin=14 * mm,
        topMargin=14 * mm, bottomMargin=14 * mm,
    )
    story = []
    story.append(Paragraph("CMR / Delivery Note", H1))
    story.append(Paragraph(
        f"Document No. <b>{d.get('cmr_no') or '—'}</b> · Proforma {d.get('doc_ref') or '—'}",
        TXT,
    ))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0B3D2E"), spaceAfter=4 * mm))

    left = (
        f"<b>Sender</b><br/>{seller.get('name') or '—'}<br/>"
        f"{seller.get('addr') or ''}<br/>{seller.get('city') or ''}<br/>"
        f"VAT: {seller.get('vat') or '—'}"
    )
    right = (
        f"<b>Consignee / Delivery</b><br/>{shipto.get('name') or '—'}<br/>"
        f"{shipto.get('addr') or ''}<br/>"
        f"{(shipto.get('zip') or '')} {shipto.get('city') or ''}<br/>"
        f"{shipto.get('country') or ''}<br/>"
        f"Buyer VAT: {buyer.get('vat') or '—'}"
    )
    parties = Table(
        [[Paragraph(left, TXT), Paragraph(right, TXT)]],
        colWidths=[90 * mm, 90 * mm],
    )
    parties.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#AAAAAA")),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CCCCCC")),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(parties)
    story.append(Spacer(1, 4 * mm))

    if carrier:
        story.append(Paragraph(
            f"<b>Carrier:</b> {carrier.get('name') or '—'} · "
            f"AWB <b>{carrier.get('awb') or '—'}</b> · "
            f"Service {carrier.get('service') or '—'} · "
            f"Pieces {carrier.get('pieces') or '—'} · "
            f"Weight {carrier.get('weight_kg') or '—'} kg",
            TXT,
        ))
    else:
        story.append(Paragraph("Carrier AWB not yet assigned.", SML))
    if d.get("goods_origin_country"):
        story.append(Paragraph(f"Country of origin: {d.get('goods_origin_country')}", TXT))
    story.append(Spacer(1, 3 * mm))

    header = [
        Paragraph("<b>#</b>", H2),
        Paragraph("<b>Description</b>", H2),
        Paragraph("<b>Qty</b>", H2),
        Paragraph("<b>Net wt (g)</b>", H2),
        Paragraph("<b>Origin</b>", H2),
    ]
    data = [header]
    for i, ln in enumerate(lines, 1):
        data.append([
            Paragraph(str(i), TXT),
            Paragraph(str(ln.get("item_type") or "—"), TXT),
            Paragraph(str(ln.get("qty") if ln.get("qty") is not None else "—"), TXT),
            Paragraph(
                f"{ln.get('net_weight'):.2f}" if ln.get("net_weight") else "—", TXT
            ),
            Paragraph(str(ln.get("origin") or "—"), TXT),
        ])
    if len(data) == 1:
        data.append([
            Paragraph("—", TXT), Paragraph("No lines", TXT),
            Paragraph("—", TXT), Paragraph("—", TXT), Paragraph("—", TXT),
        ])
    table = Table(data, colWidths=[12 * mm, 70 * mm, 25 * mm, 30 * mm, 43 * mm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B3D2E")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CCCCCC")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(table)
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(
        "This CMR / delivery note is generated from the Atlas commercial transport model. "
        "It accompanies delivery-condition confirmation and is not a fiscal invoice.",
        SML,
    ))
    doc.build(story)
    return buf.getvalue()


def cmr_available_for_draft(
    *,
    draft_id: int,
    storage_root: Path,
    proforma_db: Path,
    carrier_db: Path,
) -> bool:
    """True when a CMR number exists for the draft's outbound shipment."""
    from .shipment_document_manifest import GENERATED, build_manifest

    manifest = build_manifest(
        int(draft_id),
        storage_root=Path(storage_root),
        proforma_db=Path(proforma_db),
        carrier_db=Path(carrier_db),
    )
    for entry in ((manifest.get("groups") or {}).get("transport") or []):
        if (entry or {}).get("document_type") == "cmr" and (entry or {}).get("status") == GENERATED:
            return bool((entry or {}).get("reference"))
    return False


def export_cmr_pdf_for_draft(
    *,
    draft_id: int,
    storage_root: Path,
    proforma_db: Path,
    carrier_db: Path,
) -> Optional[Tuple[bytes, str]]:
    """Return (pdf_bytes, filename) when CMR is available; else None (no fabricate)."""
    from . import proforma_invoice_link_db as pildb
    from .carrier import doc_package
    from .carrier.cmr_number import cmr_document_number
    from .shipment_document_manifest import GENERATED, build_manifest

    storage_root = Path(storage_root)
    draft = pildb.get_draft_by_id(Path(proforma_db), int(draft_id))
    if draft is None:
        return None

    manifest = build_manifest(
        int(draft_id),
        storage_root=storage_root,
        proforma_db=Path(proforma_db),
        carrier_db=Path(carrier_db),
    )
    cmr_entry = None
    for entry in ((manifest.get("groups") or {}).get("transport") or []):
        if (entry or {}).get("document_type") == "cmr":
            cmr_entry = entry
            break
    if not cmr_entry or (cmr_entry.get("status") or "") != GENERATED:
        return None
    cmr_number = (cmr_entry.get("reference") or "").strip()
    if not cmr_number:
        return None

    company = doc_package._load_company_profile(storage_root)
    customer = doc_package._resolve_customer_from_batch(
        (draft.batch_id or "").strip(),
        (draft.client_name or "").strip(),
        storage_root,
    )

    shipment_row = None
    try:
        from .carrier.persistence import shipment_db
        from .shipment_document_manifest import _batch_client_count

        batch_id = (draft.batch_id or "").strip()
        client_name = (draft.client_name or "").strip() or None
        single_client = _batch_client_count(Path(proforma_db), batch_id) <= 1
        shipment_row = shipment_db.get_shipment_for_draft(
            Path(carrier_db),
            batch_id,
            client_name,
            allow_single_client_fallback=single_client,
        )
    except Exception as exc:
        log.debug("cmr shipment lookup failed: %s", exc)

    # Prefer cmr_number from booking idempotency when present.
    if shipment_row and not cmr_number:
        idem = (shipment_row.get("idempotency_key") or "").strip()
        cmr_number = cmr_document_number(idem) or cmr_number

    document = build_cmr_document(
        draft=draft,
        storage_root=storage_root,
        company=company,
        customer=customer,
        shipment_row=shipment_row,
        cmr_number=cmr_number,
    )
    pdf = render_cmr_pdf(document)
    if not pdf or len(pdf) < 10:
        return None
    safe = "".join(c if (c.isalnum() or c in "-_") else "_" for c in cmr_number)
    return pdf, f"cmr-{safe}.pdf"
